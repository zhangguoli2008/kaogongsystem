import asyncio
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
import threading

from PIL import Image
import pytest
from pypdf import PdfWriter
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.errors import APIError
from app.core.rate_limit import DualWindowRateLimiter
from app.main import create_app
from app.models.base import Base
from app.models.ocr_task import OCRTask
from app.models.upload import UploadedAsset
from app.models.user import User
from app.services.ocr.service import OCRService, PARAMETER_VERSION, _KeyedLocks
import app.services.ocr.service as ocr_service_module
from app.services.ocr.errors import OCRProviderError, not_configured_error
from app.services.ocr.types import Response
from app.services.ocr_contract import API_NAME


def _png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (100, 100), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _pdf_bytes(page_count: int = 2) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _polygon(left: int, top: int, right: int, bottom: int) -> dict:
    return {
        "LeftTop": {"X": left, "Y": top},
        "RightTop": {"X": right, "Y": top},
        "RightBottom": {"X": right, "Y": bottom},
        "LeftBottom": {"X": left, "Y": bottom},
    }


class FakeProvider:
    name = "fake"
    is_demo = False

    def __init__(self, *, gate: asyncio.Event | None = None) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.gate = gate
        self.pages: list[int] = []

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type
        self.calls += 1
        self.pages.append(pdf_page_number)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            else:
                await asyncio.sleep(0.01)
            return Response.model_validate(
                {
                    "QuestionInfo": [
                        {
                            "Width": 100,
                            "Height": 100,
                            "OrgWidth": 100,
                            "OrgHeight": 100,
                            "ResultList": [
                                {
                                    "Question": [
                                        {"Index": 0, "Text": "1. 测试题"}
                                    ]
                                }
                            ],
                        }
                    ],
                    "RequestId": f"fake-{self.calls}",
                }
            )
        finally:
            self.active -= 1


class CroppingProvider(FakeProvider):
    def __init__(self, *, corrected_color: str = "blue") -> None:
        super().__init__()
        self.corrected_color = corrected_color

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        corrected = base64.b64encode(_png_bytes(self.corrected_color)).decode("ascii")
        return Response.model_validate(
            {
                "QuestionInfo": [
                    {
                        "Width": 100,
                        "Height": 100,
                        "OrgWidth": 100,
                        "OrgHeight": 100,
                        "ImageBase64": corrected,
                        "ResultList": [
                            {
                                "Question": [
                                    {
                                        "Index": 0,
                                        "Text": "1. 含图测试题",
                                        "Coord": _polygon(5, 5, 95, 18),
                                    }
                                ],
                                "Option": [
                                    {
                                        "Index": 0,
                                        "Text": "A. 甲",
                                        "Coord": _polygon(10, 55, 40, 70),
                                    }
                                ],
                                "Figure": [
                                    {
                                        "Index": 0,
                                        "Text": "图形",
                                        "Coord": _polygon(-10, 20, 40, 50),
                                    }
                                ],
                                "Table": [
                                    {
                                        "Index": 0,
                                        "Text": "表格",
                                        "Coord": _polygon(50, 20, 90, 50),
                                    }
                                ],
                                "Coord": [_polygon(0, 0, 100, 80)],
                            }
                        ],
                    }
                ],
                "RequestId": f"crop-{self.calls}",
            }
        )


class FailingProvider(FakeProvider):
    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        raise OCRProviderError(
            status_code=502,
            code="OCR_PROVIDER_ERROR",
            message="OCR 服务暂时不可用",
            retryable=False,
        )


class FailsOnceProvider(FakeProvider):
    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        if self.calls == 0:
            self.calls += 1
            raise OCRProviderError(
                status_code=502,
                code="OCR_PROVIDER_ERROR",
                message="OCR 服务暂时不可用",
                retryable=True,
            )
        return await super().recognize_questions(
            file_bytes,
            filename,
            content_type,
            pdf_page_number,
        )


class ZeroAreaProvider(FakeProvider):
    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        encoded = base64.b64encode(_png_bytes("white")).decode("ascii")
        zero = _polygon(50, 50, 50, 50)
        return Response.model_validate(
            {
                "QuestionInfo": [
                    {
                        "Width": 100,
                        "Height": 100,
                        "OrgWidth": 100,
                        "OrgHeight": 100,
                        "ImageBase64": encoded,
                        "ResultList": [
                            {
                                "Question": [{"Index": 0, "Text": "1. 零面积题"}],
                                "Figure": [
                                    {"Index": 0, "Text": "零面积图", "Coord": zero}
                                ],
                                "Coord": [zero],
                            }
                        ],
                    }
                ],
                "RequestId": "zero-area",
            }
        )


class UnconfiguredProvider(FakeProvider):
    is_configured = False

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        raise not_configured_error()


class RequestIdFailingProvider(FakeProvider):
    def __init__(self, request_id: str) -> None:
        super().__init__()
        self.request_id = request_id

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        raise OCRProviderError(
            status_code=502,
            code="OCR_PROVIDER_ERROR",
            message="OCR 服务暂时不可用",
            retryable=False,
            request_id=self.request_id,
        )


class NoQuestionProvider(FakeProvider):
    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        return Response.model_validate(
            {
                "QuestionInfo": [{"ResultList": []}],
                "RequestId": "no-question-request",
            }
        )


class SizedCorrectedProvider(FakeProvider):
    def __init__(self, encoded: str) -> None:
        super().__init__()
        self.encoded = encoded

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        return Response.model_validate(
            {
                "QuestionInfo": [
                    {
                        "Width": 100,
                        "Height": 100,
                        "OrgWidth": 100,
                        "OrgHeight": 100,
                        "ImageBase64": self.encoded,
                        "ResultList": [
                            {
                                "Question": [{"Index": 0, "Text": "1. 大图测试"}],
                                "Coord": [_polygon(0, 0, 20, 20)],
                            }
                        ],
                    }
                ],
                "RequestId": "sized-corrected",
            }
        )


class MultiCorrectedProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__()
        self.encoded = base64.b64encode(_png_bytes("blue")).decode("ascii")

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        infos = []
        for number in (1, 2):
            infos.append(
                {
                    "Width": 100,
                    "Height": 100,
                    "OrgWidth": 100,
                    "OrgHeight": 100,
                    "ImageBase64": self.encoded,
                    "ResultList": [
                        {
                            "Question": [
                                {"Index": 0, "Text": f"{number}. 累计图测试"}
                            ],
                            "Coord": [_polygon(0, 0, 20, 20)],
                        }
                    ],
                }
            )
        return Response.model_validate(
            {"QuestionInfo": infos, "RequestId": "multi-corrected"}
        )


def test_dual_window_rate_limiter_atomically_enforces_minute_and_hour_limits():
    now = [0.0]
    limiter = DualWindowRateLimiter(
        minute_limit=5,
        hour_limit=50,
        clock=lambda: now[0],
    )

    assert [limiter.allow("user-1") for _ in range(5)] == [True] * 5
    assert limiter.allow("user-1") is False

    for bucket in range(1, 10):
        now[0] = bucket * 61.0
        assert [limiter.allow("user-1") for _ in range(5)] == [True] * 5
    now[0] = 10 * 61.0
    assert limiter.allow("user-1") is False

    now[0] = 3600.1
    assert limiter.allow("user-1") is True


async def _database(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'ocr.db'}",
        provider_mode="demo",
        upload_dir=tmp_path / "uploads",
        tencentcloud_ocr_max_concurrency=2,
        tencentcloud_ocr_queue_timeout_seconds=1,
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return settings, engine, factory


async def _source_asset(factory, settings, *, color="white"):
    raw = _png_bytes(color)
    storage_name = f"source-{color}.png"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / storage_name).write_bytes(raw)
    async with factory() as session:
        user = User(email=f"{color}@example.com", password_hash="hash")
        session.add(user)
        await session.flush()
        asset = UploadedAsset(
            user_id=user.id,
            storage_name=storage_name,
            original_name=storage_name,
            mime_type="image/png",
            size_bytes=len(raw),
        )
        session.add(asset)
        await session.commit()
        return user.id, asset


async def _source_asset_from_bytes(
    factory,
    settings,
    *,
    raw: bytes,
    storage_name: str,
    mime_type: str,
):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / storage_name).write_bytes(raw)
    async with factory() as session:
        user = User(email=f"{storage_name}@example.com", password_hash="hash")
        session.add(user)
        await session.flush()
        asset = UploadedAsset(
            user_id=user.id,
            storage_name=storage_name,
            original_name=storage_name,
            mime_type=mime_type,
            size_bytes=len(raw),
        )
        session.add(asset)
        await session.commit()
        return user.id, asset


async def _additional_asset(factory, settings, *, user_id: str, color: str):
    raw = _png_bytes(color)
    storage_name = f"additional-{color}.png"
    (settings.upload_dir / storage_name).write_bytes(raw)
    async with factory() as session:
        asset = UploadedAsset(
            user_id=user_id,
            storage_name=storage_name,
            original_name=storage_name,
            mime_type="image/png",
            size_bytes=len(raw),
        )
        session.add(asset)
        await session.commit()
        return asset


def test_concurrent_duplicate_across_service_instances_calls_provider_once(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, asset = await _source_asset(factory, settings)
            provider = FakeProvider()
            first_service = OCRService(provider, settings)
            second_service = OCRService(provider, settings)
            async with factory() as first_session, factory() as second_session:
                first, second = await asyncio.gather(
                    first_service.recognize(
                        first_session,
                        user_id=user_id,
                        asset=asset,
                        pdf_page_number=1,
                        local_request_id="local-1",
                    ),
                    second_service.recognize(
                        second_session,
                        user_id=user_id,
                        asset=asset,
                        pdf_page_number=1,
                        local_request_id="local-2",
                    ),
                )
            assert provider.calls == 1
            assert first.model_dump() == second.model_dump()
            async with factory() as session:
                tasks = (await session.scalars(select(OCRTask))).all()
                assert len(tasks) == 1
                assert tasks[0].status == "succeeded"
                assert tasks[0].normalized_result_json == first.model_dump(mode="json")
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_global_semaphore_caps_provider_calls_and_queue_timeout_is_safe(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        gate = asyncio.Event()
        provider = FakeProvider(gate=gate)
        service = OCRService(provider, settings)
        sources = [
            await _source_asset(factory, settings, color=color)
            for color in ("red", "green", "blue")
        ]
        sessions = [factory() for _ in sources]
        tasks = [
            asyncio.create_task(
                service.recognize(
                    session,
                    user_id=user_id,
                    asset=asset,
                    pdf_page_number=1,
                    local_request_id=f"local-{index}",
                )
            )
            for index, (session, (user_id, asset)) in enumerate(
                zip(sessions[:2], sources[:2])
            )
        ]
        try:
            for _ in range(100):
                if provider.active == 2:
                    break
                await asyncio.sleep(0.01)
            assert provider.active == 2
            assert provider.max_active == 2
            third_user_id, third_asset = sources[2]
            third = asyncio.create_task(
                service.recognize(
                    sessions[2],
                    user_id=third_user_id,
                    asset=third_asset,
                    pdf_page_number=1,
                    local_request_id="local-2",
                )
            )
            tasks.append(third)
            with pytest.raises(APIError) as caught:
                await third
            assert caught.value.status_code == 429
            assert caught.value.code == "OCR_RATE_LIMITED"
            assert "繁忙" in caught.value.message
        finally:
            gate.set()
            await asyncio.gather(*tasks[:2])
            for session in sessions:
                await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_crops_corrected_image_and_persists_only_normalized_asset_references(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            provider = CroppingProvider(corrected_color="blue")
            service = OCRService(provider, settings)
            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="crop-local",
                )

            question = result.questions[0]
            assert question.crop_asset_id is not None
            assert question.crop_image_url == f"/uploads/{question.crop_asset_id}"
            assert question.figures[0].asset_id is not None
            assert question.tables[0].asset_id is not None
            assert question.options[0].asset_id is not None
            assert any("越界" in warning for warning in question.warnings)

            async with factory() as session:
                assets = (
                    await session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
                tasks = (await session.scalars(select(OCRTask))).all()
            assert len(assets) == 5
            generated = {asset.id: asset for asset in assets if asset.id != source.id}
            assert set(generated) == {
                question.crop_asset_id,
                question.figures[0].asset_id,
                question.tables[0].asset_id,
                question.options[0].asset_id,
            }
            for asset in generated.values():
                assert asset.mime_type == "image/png"
                assert asset.storage_name.endswith(".png")
            with Image.open(
                settings.upload_dir / generated[question.crop_asset_id].storage_name
            ) as crop:
                assert crop.getpixel((0, 0)) == (0, 0, 255)

            persisted = json.dumps(tasks[0].normalized_result_json, ensure_ascii=False)
            assert "ImageBase64" not in persisted
            assert "image_base64" not in persisted
            assert str(tmp_path) not in persisted

            before_names = {path.name for path in settings.upload_dir.iterdir()}
            async with factory() as session:
                cached = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="crop-cached",
                )
            assert cached.model_dump() == result.model_dump()
            assert provider.calls == 1
            assert {path.name for path in settings.upload_dir.iterdir()} == before_names
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_generated_crop_failure_cleans_files_and_rolls_back_assets(
    tmp_path, monkeypatch
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            provider = CroppingProvider()
            service = OCRService(provider, settings)
            real_save = ocr_service_module.save_generated_png
            calls = 0

            def fail_second(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("disk full: private-path-must-not-leak")
                return real_save(*args, **kwargs)

            monkeypatch.setattr(ocr_service_module, "save_generated_png", fail_second)
            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="crop-failure",
                    )
            assert caught.value.code == "OCR_PROCESSING_FAILED"
            assert "private-path" not in caught.value.message

            async with factory() as session:
                assets = (
                    await session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
                task = await session.scalar(select(OCRTask))
            assert [asset.id for asset in assets] == [source.id]
            assert {path.name for path in settings.upload_dir.iterdir()} == {
                source.storage_name
            }
            assert task is not None
            assert task.status == "failed"
            assert task.error_code == "OCR_PROCESSING_FAILED"
            assert "private-path" not in (task.error_message or "")
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_pdf_without_corrected_image_keeps_original_and_warns(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset_from_bytes(
                factory,
                settings,
                raw=_pdf_bytes(2),
                storage_name="source.pdf",
                mime_type="application/pdf",
            )
            provider = FakeProvider()
            service = OCRService(provider, settings)
            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=2,
                    local_request_id="pdf-no-crop",
                )
            assert result.questions[0].crop_asset_id is None
            assert any(
                "PDF" in warning and "原文件" in warning
                for warning in result.warnings
            )
            async with factory() as session:
                assets = (
                    await session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
            assert [asset.id for asset in assets] == [source.id]
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_provider_failure_persists_safe_failed_task_without_generated_files(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            provider = FailingProvider()
            service = OCRService(provider, settings)
            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="provider-failure",
                    )
            assert caught.value.code == "OCR_PROVIDER_ERROR"
            async with factory() as session:
                task = await session.scalar(select(OCRTask))
                assets = (
                    await session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
            assert task is not None
            assert task.status == "failed"
            assert task.error_code == "OCR_PROVIDER_ERROR"
            assert task.error_message == "OCR 服务暂时不可用"
            assert [asset.id for asset in assets] == [source.id]
            assert {path.name for path in settings.upload_dir.iterdir()} == {
                source.storage_name
            }
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_failed_task_retries_same_record_and_then_reuses_success(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FailsOnceProvider()
            service = OCRService(provider, settings)
            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="retry-failed",
                    )
            assert caught.value.code == "OCR_PROVIDER_ERROR"
            async with factory() as session:
                failed = await session.scalar(select(OCRTask))
                assert failed is not None
                failed_id = failed.id
                assert failed.status == "failed"

            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="retry-success",
                )
            async with factory() as session:
                tasks = (await session.scalars(select(OCRTask))).all()
            assert provider.calls == 2
            assert len(tasks) == 1
            assert tasks[0].id == failed_id
            assert tasks[0].status == "succeeded"

            async with factory() as session:
                cached = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="retry-cached",
                )
            assert cached.model_dump() == result.model_dump()
            assert provider.calls == 2
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_success_cache_does_not_consume_user_provider_rate_limit(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            other = await _additional_asset(
                factory, settings, user_id=user_id, color="black"
            )
            provider = FakeProvider()
            limiter = DualWindowRateLimiter(minute_limit=1, hour_limit=50)
            service = OCRService(provider, settings, rate_limiter=limiter)
            async with factory() as session:
                first = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="rate-first",
                )
            async with factory() as session:
                cached = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="rate-cached",
                )
            assert cached.model_dump() == first.model_dump()
            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=other,
                        pdf_page_number=1,
                        local_request_id="rate-new-file",
                    )
            assert caught.value.code == "OCR_RATE_LIMITED"
            assert provider.calls == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_persisted_processing_task_returns_safe_in_progress_and_releases_key_lock(
    tmp_path,
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            raw = (settings.upload_dir / source.storage_name).read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            material = "\x1f".join(
                (user_id, source_hash, "1", provider.name, PARAMETER_VERSION)
            )
            key = hashlib.sha256(material.encode("utf-8")).hexdigest()
            async with factory() as session:
                session.add(
                    OCRTask(
                        user_id=user_id,
                        source_file_id=source.id,
                        provider=provider.name,
                        api_name=API_NAME,
                        source_file_hash=source_hash,
                        pdf_page_number=1,
                        parameter_version=PARAMETER_VERSION,
                        idempotency_key=key,
                        status="processing",
                    )
                )
                await session.commit()
            service = OCRService(provider, settings)
            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="already-processing",
                    )
            assert caught.value.status_code == 409
            assert caught.value.code == "OCR_IN_PROGRESS"
            assert provider.calls == 0
            assert key not in _KeyedLocks._entries
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("page_number", [0, 3])
def test_pdf_page_is_checked_against_real_file(page_number, tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset_from_bytes(
                factory,
                settings,
                raw=_pdf_bytes(2),
                storage_name="real-pages.pdf",
                mime_type="application/pdf",
            )
            provider = FakeProvider()
            service = OCRService(provider, settings)
            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=page_number,
                        local_request_id="invalid-page",
                    )
            assert caught.value.status_code == 422
            assert caught.value.code == "OCR_INVALID_PDF_PAGE"
            assert provider.calls == 0
            async with factory() as session:
                assert await session.scalar(select(OCRTask)) is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_zero_area_crop_keeps_question_and_media(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            service = OCRService(ZeroAreaProvider(), settings)
            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="zero-area",
                )
            assert result.question_count == 1
            assert len(result.questions) == 1
            assert len(result.questions[0].figures) == 1
            assert result.questions[0].crop_asset_id is None
            assert result.questions[0].figures[0].asset_id is None
            assert any(
                "没有有效面积" in warning
                for warning in result.questions[0].warnings
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_cancellation_releases_provider_semaphore_and_marks_task_failed(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(
            update={"tencentcloud_ocr_max_concurrency": 1}
        )
        gate = asyncio.Event()
        provider = FakeProvider(gate=gate)
        service = OCRService(provider, settings)
        first_user, first_source = await _source_asset(factory, settings, color="red")
        second_user, second_source = await _source_asset(
            factory, settings, color="green"
        )
        first_session = factory()
        second_session = factory()
        first = asyncio.create_task(
            service.recognize(
                first_session,
                user_id=first_user,
                asset=first_source,
                pdf_page_number=1,
                local_request_id="cancel-first",
            )
        )
        try:
            await asyncio.wait_for(provider.started.wait(), timeout=1)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            gate.set()
            result = await service.recognize(
                second_session,
                user_id=second_user,
                asset=second_source,
                pdf_page_number=1,
                local_request_id="cancel-second",
            )
            assert result.question_count == 1
            async with factory() as session:
                tasks = (await session.scalars(select(OCRTask))).all()
            assert sorted(task.status for task in tasks) == ["failed", "succeeded"]
        finally:
            gate.set()
            await first_session.close()
            await second_session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_create_app_builds_one_reusable_ocr_service_without_live_credentials(
    tmp_path,
):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'app.db'}",
        provider_mode="demo",
        ocr_provider="tencent_question_split",
        tencentcloud_secret_id=None,
        tencentcloud_secret_key=None,
        upload_dir=tmp_path / "uploads",
    )

    app = create_app(settings)

    assert app.state.ocr_provider.name == "tencent_question_split"
    assert app.state.ocr_service._provider is app.state.ocr_provider


def test_failed_task_claim_is_atomic_without_process_key_lock(tmp_path):
    class ScalarBarrierSession:
        def __init__(self, session, barrier) -> None:
            self._session = session
            self._barrier = barrier

        async def scalar(self, *args, **kwargs):
            value = await self._session.scalar(*args, **kwargs)
            self._barrier["count"] += 1
            if self._barrier["count"] == 2:
                self._barrier["ready"].set()
            await asyncio.wait_for(self._barrier["ready"].wait(), timeout=2)
            return value

        def __getattr__(self, name):
            return getattr(self._session, name)

    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            raw = (settings.upload_dir / source.storage_name).read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            key = service._idempotency_key(
                user_id=user_id,
                source_hash=source_hash,
                pdf_page_number=1,
            )
            async with factory() as session:
                session.add(
                    OCRTask(
                        user_id=user_id,
                        source_file_id=source.id,
                        provider=provider.name,
                        api_name=API_NAME,
                        source_file_hash=source_hash,
                        pdf_page_number=1,
                        parameter_version=PARAMETER_VERSION,
                        idempotency_key=key,
                        status="failed",
                        error_code="OCR_PROVIDER_ERROR",
                        error_message="OCR 服务暂时不可用",
                    )
                )
                await session.commit()

            first_session = factory()
            second_session = factory()
            barrier = {"count": 0, "ready": asyncio.Event()}
            try:
                outcomes = await asyncio.gather(
                    service._claim_task(
                        ScalarBarrierSession(first_session, barrier),
                        user_id=user_id,
                        asset=source,
                        source_hash=source_hash,
                        pdf_page_number=1,
                        idempotency_key=key,
                    ),
                    service._claim_task(
                        ScalarBarrierSession(second_session, barrier),
                        user_id=user_id,
                        asset=source,
                        source_hash=source_hash,
                        pdf_page_number=1,
                        idempotency_key=key,
                    ),
                    return_exceptions=True,
                )
            finally:
                await first_session.close()
                await second_session.close()

            claims = [outcome for outcome in outcomes if isinstance(outcome, tuple)]
            errors = [outcome for outcome in outcomes if isinstance(outcome, APIError)]
            assert len(claims) == 1
            assert len(errors) == 1
            assert errors[0].code == "OCR_IN_PROGRESS"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_failed_task_claim_statement_compiles_for_sqlite_and_postgresql():
    statement = ocr_service_module._failed_task_claim_statement("key-123")

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = str(
            statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        ).lower()
        assert "update ocr_tasks" in compiled
        assert "idempotency_key" in compiled
        assert "status = 'failed'" in compiled


def test_dual_window_clock_is_sampled_inside_the_atomic_section():
    first_clock_called = threading.Event()
    second_clock_called = threading.Event()
    release_first_clock = threading.Event()
    call_guard = threading.Lock()
    calls = 0

    def ordered_clock() -> float:
        nonlocal calls
        with call_guard:
            position = calls
            calls += 1
        if position == 0:
            first_clock_called.set()
            assert release_first_clock.wait(timeout=2)
            return 5.0
        second_clock_called.set()
        return 10.0

    limiter = DualWindowRateLimiter(
        minute_limit=5,
        hour_limit=50,
        clock=ordered_clock,
    )
    first = threading.Thread(target=limiter.allow, args=("user",))
    second = threading.Thread(target=limiter.allow, args=("user",))

    first.start()
    assert first_clock_called.wait(timeout=1)
    second.start()
    second_clock_called.wait(timeout=0.5)
    release_first_clock.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert list(limiter._attempts["user"]) == [5.0, 10.0]


def test_image_page_number_is_normalized_to_one_and_reuses_cache(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            async with factory() as session:
                first = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=9,
                    local_request_id="image-page-nine",
                )
            async with factory() as session:
                cached = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="image-page-one",
                )
            async with factory() as session:
                task = await session.scalar(select(OCRTask))
            assert provider.calls == 1
            assert provider.pages == [1]
            assert first.page_number == cached.page_number == 1
            assert task is not None
            assert task.pdf_page_number == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_unconfigured_provider_preflight_never_consumes_user_limit(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = UnconfiguredProvider()
            limiter = DualWindowRateLimiter(minute_limit=1, hour_limit=1)
            service = OCRService(provider, settings, rate_limiter=limiter)
            for attempt in range(3):
                async with factory() as session:
                    with pytest.raises(APIError) as caught:
                        await service.recognize(
                            session,
                            user_id=user_id,
                            asset=source,
                            pdf_page_number=1,
                            local_request_id=f"not-configured-{attempt}",
                        )
                assert caught.value.code == "OCR_NOT_CONFIGURED"
            assert provider.calls == 0
            assert "user" not in limiter._attempts
            assert user_id not in limiter._attempts
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("request_id", "expected"),
    [
        (
            "123e4567-e89b-12d3-a456-426614174000",
            "123e4567-e89b-12d3-a456-426614174000",
        ),
        ("AKID-example-secret-shaped-value", None),
        ("unsafe\nraw-base64", None),
    ],
)
def test_provider_error_persists_and_logs_only_safe_request_id(
    request_id, expected, tmp_path, caplog
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            service = OCRService(RequestIdFailingProvider(request_id), settings)
            with caplog.at_level("INFO", logger="app.services.ocr.service"):
                async with factory() as session:
                    with pytest.raises(APIError):
                        await service.recognize(
                            session,
                            user_id=user_id,
                            asset=source,
                            pdf_page_number=1,
                            local_request_id="request-id-failure",
                        )
            async with factory() as session:
                task = await session.scalar(select(OCRTask))
            assert task is not None
            assert task.provider_request_id == expected
            completion = [
                record
                for record in caplog.records
                if record.message == "OCR request completed"
            ][-1]
            assert completion.provider_request_id == expected
            if expected is None:
                assert request_id not in caplog.text
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_no_question_uses_prd_error_code(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            service = OCRService(NoQuestionProvider(), settings)
            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="no-question",
                    )
            assert caught.value.code == "OCR_NO_QUESTION"
            async with factory() as session:
                task = await session.scalar(select(OCRTask))
            assert task is not None
            assert task.error_code == "OCR_NO_QUESTION"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_oversized_corrected_base64_is_skipped_before_decode(
    tmp_path, monkeypatch, caplog
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(
            update={
                "ocr_corrected_image_max_bytes": 16,
                "ocr_corrected_images_max_total_bytes": 16,
            }
        )
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            encoded = base64.b64encode(_png_bytes("blue")).decode("ascii")
            provider = SizedCorrectedProvider(encoded)

            def forbidden_decode(*args, **kwargs):
                raise AssertionError("oversized corrected Base64 was decoded")

            monkeypatch.setattr(
                "app.services.ocr.cropper.base64.b64decode", forbidden_decode
            )
            service = OCRService(provider, settings)
            with caplog.at_level("INFO", logger="app.services.ocr.service"):
                async with factory() as session:
                    result = await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="oversized-corrected",
                    )
            assert any("大小上限" in warning for warning in result.warnings)
            async with factory() as session:
                crop_asset = await session.get(
                    UploadedAsset, result.questions[0].crop_asset_id
                )
            assert crop_asset is not None
            with Image.open(settings.upload_dir / crop_asset.storage_name) as crop:
                assert crop.getpixel((0, 0)) == (255, 0, 0)
            assert encoded not in caplog.text
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_corrected_images_enforce_per_response_total_budget(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        provider = MultiCorrectedProvider()
        decoded_size = len(_png_bytes("blue"))
        settings = settings.model_copy(
            update={
                "ocr_corrected_image_max_bytes": decoded_size + 1,
                "ocr_corrected_images_max_total_bytes": decoded_size + 1,
            }
        )
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            service = OCRService(provider, settings)
            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="corrected-total-budget",
                )
            assert result.question_count == 2
            assert any("累计大小上限" in warning for warning in result.warnings)
            async with factory() as session:
                first_asset = await session.get(
                    UploadedAsset, result.questions[0].crop_asset_id
                )
                second_asset = await session.get(
                    UploadedAsset, result.questions[1].crop_asset_id
                )
            assert first_asset is not None
            assert second_asset is not None
            with Image.open(settings.upload_dir / first_asset.storage_name) as first:
                assert first.getpixel((0, 0)) == (0, 0, 255)
            with Image.open(settings.upload_dir / second_asset.storage_name) as second:
                assert second.getpixel((0, 0)) == (255, 0, 0)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_crop_artifact_count_budget_skips_excess_assets(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(update={"ocr_crop_max_artifacts": 2})
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            service = OCRService(CroppingProvider(), settings)
            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="artifact-count-budget",
                )
            async with factory() as session:
                assets = (
                    await session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
            assert len(assets) == 3
            assert result.question_count == 1
            assert any("裁剪图片数量上限" in warning for warning in result.warnings)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_crop_png_total_byte_budget_skips_before_allocating_crop(
    tmp_path, monkeypatch
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(update={"ocr_crop_max_total_png_bytes": 1})
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            service = OCRService(CroppingProvider(), settings)

            def forbidden_crop(*args, **kwargs):
                raise AssertionError("oversized crop was allocated")

            monkeypatch.setattr(
                "app.services.ocr.cropper.Image.Image.crop", forbidden_crop
            )
            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="artifact-byte-budget",
                )
            async with factory() as session:
                assets = (
                    await session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
            assert [asset.id for asset in assets] == [source.id]
            assert result.question_count == 1
            assert result.questions[0].crop_asset_id is None
            assert any(
                "内存预算" in warning
                for warning in result.questions[0].warnings
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_cancellation_during_crop_write_waits_then_cleans_file_and_row(
    tmp_path, monkeypatch, caplog
):
    write_started = threading.Event()
    release_write = threading.Event()
    real_save = ocr_service_module.save_generated_png

    def slow_save(*args, **kwargs):
        write_started.set()
        assert release_write.wait(timeout=3)
        return real_save(*args, **kwargs)

    monkeypatch.setattr(ocr_service_module, "save_generated_png", slow_save)

    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        session = factory()
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            service = OCRService(CroppingProvider(), settings)
            with caplog.at_level("INFO", logger="app.services.ocr.service"):
                pending = asyncio.create_task(
                    service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="cancel-during-write",
                    )
                )
                assert await asyncio.to_thread(write_started.wait, 2)
                pending.cancel()
                await asyncio.sleep(0)
                release_write.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            async with factory() as check_session:
                assets = (
                    await check_session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
                task = await check_session.scalar(select(OCRTask))
            assert [asset.id for asset in assets] == [source.id]
            assert task is not None
            assert task.status == "failed"
            assert task.error_code == "OCR_CANCELLED"
            assert sorted(path.name for path in settings.upload_dir.iterdir()) == [
                source.storage_name
            ]
            completion = [
                record
                for record in caplog.records
                if record.message == "OCR request completed"
            ][-1]
            assert completion.error_code == "OCR_CANCELLED"
            assert completion.success is False
            assert completion.pdf_page_number == 1
            assert isinstance(completion.duration_ms, int)
        finally:
            release_write.set()
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_successful_but_ambiguous_commit_keeps_committed_assets_and_cache(tmp_path):
    class CommitUnknownSession:
        def __init__(self, session) -> None:
            self._session = session
            self.commit_calls = 0

        async def commit(self):
            self.commit_calls += 1
            await self._session.commit()
            if self.commit_calls == 3:
                raise OSError("commit result unavailable")

        def __getattr__(self, name):
            return getattr(self._session, name)

    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            provider = CroppingProvider()
            service = OCRService(provider, settings)
            async with factory() as real_session:
                wrapped = CommitUnknownSession(real_session)
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        wrapped,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="ambiguous-commit",
                    )
            assert caught.value.code == "OCR_PROCESSING_FAILED"

            async with factory() as check_session:
                task = await check_session.scalar(select(OCRTask))
                assets = (
                    await check_session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
            assert task is not None
            assert task.status == "succeeded"
            assert task.normalized_result_json is not None
            generated = [asset for asset in assets if asset.id != source.id]
            assert generated
            assert all(
                (settings.upload_dir / asset.storage_name).is_file()
                for asset in generated
            )

            async with factory() as retry_session:
                cached = await service.recognize(
                    retry_session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="ambiguous-commit-retry",
                )
            assert cached.question_count == 1
            assert provider.calls == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())
