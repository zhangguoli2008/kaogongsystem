import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from io import BytesIO
from pathlib import Path
import threading

from PIL import Image
import pytest
from pypdf import PdfWriter
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
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
                                {"Question": [{"Index": 0, "Text": "1. 测试题"}]}
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


class GatedCroppingProvider(CroppingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        self.started.set()
        await self.release.wait()
        return await super().recognize_questions(
            file_bytes,
            filename,
            content_type,
            pdf_page_number,
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


class GatedFailingProvider(FailingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        self.started.set()
        await self.release.wait()
        return await super().recognize_questions(
            file_bytes,
            filename,
            content_type,
            pdf_page_number,
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
    def __init__(self, request_id: str = "no-question-request") -> None:
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
        return Response.model_validate(
            {
                "QuestionInfo": [{"ResultList": []}],
                "RequestId": self.request_id,
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
                            "Question": [{"Index": 0, "Text": f"{number}. 累计图测试"}],
                            "Coord": [_polygon(0, 0, 20, 20)],
                        }
                    ],
                }
            )
        return Response.model_validate(
            {"QuestionInfo": infos, "RequestId": "multi-corrected"}
        )


class MissingCoordMediaProvider(FakeProvider):
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
                        "ResultList": [
                            {
                                "Question": [
                                    {
                                        "Index": 0,
                                        "Text": "1. 大量无坐标图形",
                                        "Coord": _polygon(0, 0, 20, 20),
                                    }
                                ],
                                "Figure": [
                                    {"Index": index, "Text": f"图形 {index}"}
                                    for index in range(25)
                                ],
                                "Coord": [_polygon(0, 0, 20, 20)],
                            }
                        ],
                    }
                ],
                "RequestId": "missing-coord-media",
            }
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
                zip(sessions[:2], sources[:2], strict=True)
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


def test_global_semaphore_covers_normalize_crop_persist_and_terminal_cas(
    tmp_path, monkeypatch
):
    first_crop_started = threading.Event()
    second_crop_started = threading.Event()
    release_first_crop = threading.Event()
    call_guard = threading.Lock()
    crop_calls = 0
    real_build_crop_batch = ocr_service_module.build_crop_batch

    def blocking_build_crop_batch(*args, **kwargs):
        nonlocal crop_calls
        with call_guard:
            crop_calls += 1
            position = crop_calls
        if position == 1:
            first_crop_started.set()
            assert release_first_crop.wait(timeout=3)
        else:
            second_crop_started.set()
        return real_build_crop_batch(*args, **kwargs)

    monkeypatch.setattr(
        ocr_service_module,
        "build_crop_batch",
        blocking_build_crop_batch,
    )

    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(update={"tencentcloud_ocr_max_concurrency": 1})
        first_session = factory()
        second_session = factory()
        first_request = None
        second_request = None
        try:
            user_id, first_source = await _source_asset(factory, settings)
            second_source = await _additional_asset(
                factory,
                settings,
                user_id=user_id,
                color="green",
            )
            provider = FakeProvider()
            service = OCRService(provider, settings)
            first_request = asyncio.create_task(
                service.recognize(
                    first_session,
                    user_id=user_id,
                    asset=first_source,
                    pdf_page_number=1,
                    local_request_id="crop-concurrency-first",
                )
            )
            assert await asyncio.to_thread(first_crop_started.wait, 2)

            second_request = asyncio.create_task(
                service.recognize(
                    second_session,
                    user_id=user_id,
                    asset=second_source,
                    pdf_page_number=1,
                    local_request_id="crop-concurrency-second",
                )
            )
            assert not await asyncio.to_thread(second_crop_started.wait, 0.5)
            assert provider.calls == 1

            release_first_crop.set()
            first, second = await asyncio.gather(first_request, second_request)
            assert first.question_count == second.question_count == 1
            assert crop_calls == 2
        finally:
            release_first_crop.set()
            pending = [
                request
                for request in (first_request, second_request)
                if request is not None and not request.done()
            ]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await first_session.close()
            await second_session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_cancellation_during_crop_compute_holds_semaphore_until_worker_stops(
    tmp_path, monkeypatch
):
    first_crop_started = threading.Event()
    release_first_crop = threading.Event()
    second_crop_started = threading.Event()
    real_build_crop_batch = ocr_service_module.build_crop_batch
    call_lock = threading.Lock()
    calls = 0

    def controlled_build_crop_batch(*args, **kwargs):
        nonlocal calls
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_crop_started.set()
            assert release_first_crop.wait(timeout=5)
        else:
            second_crop_started.set()
        return real_build_crop_batch(*args, **kwargs)

    monkeypatch.setattr(
        ocr_service_module,
        "build_crop_batch",
        controlled_build_crop_batch,
    )

    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(update={"tencentcloud_ocr_max_concurrency": 1})
        first_session = factory()
        second_session = factory()
        first_request = None
        second_request = None
        try:
            user_id, first_source = await _source_asset(factory, settings)
            second_source = await _additional_asset(
                factory,
                settings,
                user_id=user_id,
                color="green",
            )
            provider = FakeProvider()
            service = OCRService(provider, settings)
            first_request = asyncio.create_task(
                service.recognize(
                    first_session,
                    user_id=user_id,
                    asset=first_source,
                    pdf_page_number=1,
                    local_request_id="cancel-crop-compute-first",
                )
            )
            assert await asyncio.to_thread(first_crop_started.wait, 2)
            first_request.cancel()
            await asyncio.sleep(0)

            second_request = asyncio.create_task(
                service.recognize(
                    second_session,
                    user_id=user_id,
                    asset=second_source,
                    pdf_page_number=1,
                    local_request_id="cancel-crop-compute-second",
                )
            )
            assert not await asyncio.to_thread(second_crop_started.wait, 0.3)
            assert provider.calls == 1
            assert not first_request.done()

            release_first_crop.set()
            with pytest.raises(asyncio.CancelledError):
                await first_request
            result = await second_request
            assert result.question_count == 1
            assert second_crop_started.is_set()

            async with factory() as check_session:
                tasks = (
                    await check_session.scalars(
                        select(OCRTask).order_by(OCRTask.source_file_id)
                    )
                ).all()
            statuses = {task.source_file_id: task.status for task in tasks}
            assert statuses[first_source.id] == "failed"
            assert statuses[second_source.id] == "succeeded"
        finally:
            release_first_crop.set()
            for request in (first_request, second_request):
                if request is not None and not request.done():
                    request.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await request
            await first_session.close()
            await second_session.close()
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
                "PDF" in warning and "原文件" in warning for warning in result.warnings
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


def test_expired_processing_task_is_reclaimed_by_a_new_request(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            task = await _seed_processing_ocr_task(
                factory,
                service,
                user_id,
                source,
                claim_token="expired-owner-token",
                updated_at=datetime.now(timezone.utc)
                - timedelta(seconds=settings.ocr_processing_lease_seconds + 1),
            )

            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="reclaim-expired-processing",
                )

            assert result.question_count == 1
            assert provider.calls == 1
            async with factory() as session:
                persisted = await session.get(OCRTask, task.id)
            assert persisted is not None
            assert persisted.status == "succeeded"
            assert persisted.provider_request_id == result.request_id
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_unexpired_processing_task_is_not_reclaimed(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            task = await _seed_processing_ocr_task(
                factory,
                service,
                user_id,
                source,
                claim_token="current-owner-token",
                updated_at=datetime.now(timezone.utc),
            )

            async with factory() as session:
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="preserve-current-processing",
                    )

            assert caught.value.status_code == 409
            assert caught.value.code == "OCR_IN_PROGRESS"
            assert provider.calls == 0
            async with factory() as session:
                persisted = await session.get(OCRTask, task.id)
            assert persisted is not None
            assert persisted.status == "processing"
            assert persisted.provider_request_id == "current-owner-token"
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
                "没有有效面积" in warning for warning in result.questions[0].warnings
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_cancellation_releases_provider_semaphore_and_marks_task_failed(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(update={"tencentcloud_ocr_max_concurrency": 1})
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

            claims = [
                outcome
                for outcome in outcomes
                if not isinstance(outcome, BaseException)
            ]
            errors = [outcome for outcome in outcomes if isinstance(outcome, APIError)]
            assert len(claims) == 1
            assert len(errors) == 1
            assert errors[0].code == "OCR_IN_PROGRESS"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_claimable_task_statement_compiles_for_sqlite_and_postgresql():
    statement = ocr_service_module._claimable_task_statement(
        "key-123",
        "new-owner-token",
        datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = str(
            statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        ).lower()
        assert "update ocr_tasks" in compiled
        assert "idempotency_key" in compiled
        assert "status = 'failed'" in compiled
        assert "status = 'processing'" in compiled
        assert "updated_at" in compiled


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


def test_post_response_failure_discards_unsafe_request_id_from_db_and_logs(
    tmp_path, caplog
):
    unsafe_request_id = "AKID-secret-shaped-post-response-request-id"

    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            service = OCRService(NoQuestionProvider(unsafe_request_id), settings)
            with caplog.at_level("INFO", logger="app.services.ocr.service"):
                async with factory() as session:
                    with pytest.raises(APIError) as caught:
                        await service.recognize(
                            session,
                            user_id=user_id,
                            asset=source,
                            pdf_page_number=1,
                            local_request_id="unsafe-post-response-request-id",
                        )
            assert caught.value.code == "OCR_NO_QUESTION"
            async with factory() as session:
                task = await session.scalar(select(OCRTask))
            assert task is not None
            assert task.status == "failed"
            assert task.provider_request_id is None
            assert unsafe_request_id not in caplog.text
            assert unsafe_request_id not in " ".join(
                str(vars(record)) for record in caplog.records
            )
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


def test_crop_attempt_budget_bounds_invalid_media_and_warning_growth(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        settings = settings.model_copy(update={"ocr_crop_max_artifacts": 2})
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            service = OCRService(MissingCoordMediaProvider(), settings)
            async with factory() as session:
                result = await service.recognize(
                    session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="invalid-media-attempt-budget",
                )

            question = result.questions[0]
            assert question.crop_asset_id is not None
            assert len(question.figures) == 25
            assert all(figure.asset_id is None for figure in question.figures)
            assert sum("缺少有效坐标" in warning for warning in question.warnings) == 1
            assert (
                sum("裁剪图片数量上限" in warning for warning in result.warnings) == 1
            )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_crop_png_total_byte_budget_skips_before_allocating_crop(tmp_path, monkeypatch):
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
                "内存预算" in warning for warning in result.questions[0].warnings
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


def test_cancellation_during_failure_cleanup_waits_and_marks_task_failed(tmp_path):
    class BlockingRollbackSession:
        def __init__(self, session) -> None:
            self._session = session
            self.rollback_started = asyncio.Event()
            self.release_rollback = asyncio.Event()
            self.rollback_calls = 0

        async def rollback(self):
            self.rollback_calls += 1
            if self.rollback_calls == 1:
                self.rollback_started.set()
                await self.release_rollback.wait()
            await self._session.rollback()

        def __getattr__(self, name):
            return getattr(self._session, name)

    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            async with factory() as real_session:
                session = BlockingRollbackSession(real_session)
                service = OCRService(FailingProvider(), settings)
                pending = asyncio.create_task(
                    service.recognize(
                        session,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="cancel-failure-cleanup",
                    )
                )
                await asyncio.wait_for(session.rollback_started.wait(), timeout=2)
                pending.cancel()
                await asyncio.sleep(0)
                assert not pending.done()
                session.release_rollback.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            async with factory() as check_session:
                task = await check_session.scalar(select(OCRTask))
            assert task is not None
            assert task.status == "failed"
            assert task.error_code == "OCR_PROVIDER_ERROR"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_failure_cleanup_removes_worker_files_even_when_database_rollback_fails(
    tmp_path,
):
    class RollbackFailureSession:
        async def rollback(self):
            raise OSError("database unavailable")

    async def scenario():
        settings, engine, _ = await _database(tmp_path)
        try:
            storage_name = "failed-worker-crop.png"
            generated_path = settings.upload_dir / storage_name
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            generated_path.write_bytes(_png_bytes())
            service = OCRService(FakeProvider(), settings)

            with pytest.raises(OSError, match="database unavailable"):
                await service._mark_failed(
                    RollbackFailureSession(),
                    "task-id",
                    "claim-token",
                    APIError(500, "OCR_PROCESSING_FAILED", "OCR 结果处理失败"),
                    generated_assets=[("asset-id", storage_name)],
                    provider_request_id=None,
                    preserve_committed_success=False,
                )

            assert not generated_path.exists()
        finally:
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


class ClaimCommitSession:
    """Control one commit after its database side effect for claim regressions."""

    def __init__(
        self,
        session,
        *,
        target_commit: int,
        block_after_commit: bool = False,
        raise_after_commit: bool = False,
        late_exception: Exception | None = None,
    ) -> None:
        self._session = session
        self._target_commit = target_commit
        self._block_after_commit = block_after_commit
        self._raise_after_commit = raise_after_commit
        self._late_exception = late_exception
        self.commit_calls = 0
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    async def commit(self):
        self.commit_calls += 1
        await self._session.commit()
        if self.commit_calls != self._target_commit:
            return
        self.committed.set()
        if self._block_after_commit:
            await self.release.wait()
        if self._late_exception is not None:
            raise self._late_exception
        if self._raise_after_commit:
            raise OSError("claim commit result unavailable")

    def __getattr__(self, name):
        return getattr(self._session, name)


class BlockScalarAfterReadSession:
    """Pause one scalar result after the database read has completed."""

    def __init__(self, session, *, target_scalar: int) -> None:
        self._session = session
        self._target_scalar = target_scalar
        self.scalar_calls = 0
        self.read = asyncio.Event()
        self.release = asyncio.Event()

    async def scalar(self, *args, **kwargs):
        value = await self._session.scalar(*args, **kwargs)
        self.scalar_calls += 1
        if self.scalar_calls == self._target_scalar:
            self.read.set()
            await self.release.wait()
        return value

    def __getattr__(self, name):
        return getattr(self._session, name)


async def _seed_failed_ocr_task(factory, service, user_id, source) -> OCRTask:
    raw = Path(service._settings.upload_dir / source.storage_name).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    key = service._idempotency_key(
        user_id=user_id,
        source_hash=source_hash,
        pdf_page_number=1,
    )
    async with factory() as session:
        task = OCRTask(
            user_id=user_id,
            source_file_id=source.id,
            provider=service._provider.name,
            api_name=API_NAME,
            source_file_hash=source_hash,
            pdf_page_number=1,
            parameter_version=PARAMETER_VERSION,
            idempotency_key=key,
            status="failed",
            error_code="OCR_PROVIDER_ERROR",
            error_message="OCR 服务暂时不可用",
        )
        session.add(task)
        await session.commit()
        return task


async def _seed_processing_ocr_task(
    factory,
    service,
    user_id,
    source,
    *,
    claim_token: str,
    updated_at: datetime,
) -> OCRTask:
    raw = Path(service._settings.upload_dir / source.storage_name).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    key = service._idempotency_key(
        user_id=user_id,
        source_hash=source_hash,
        pdf_page_number=1,
    )
    async with factory() as session:
        task = OCRTask(
            user_id=user_id,
            source_file_id=source.id,
            provider=service._provider.name,
            api_name=API_NAME,
            source_file_hash=source_hash,
            pdf_page_number=1,
            parameter_version=PARAMETER_VERSION,
            idempotency_key=key,
            status="processing",
            provider_request_id=claim_token,
            updated_at=updated_at,
        )
        session.add(task)
        await session.commit()
        return task


def test_late_success_cannot_overwrite_reclaimed_then_cancelled_task(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        old_session = factory()
        try:
            user_id, source = await _source_asset(factory, settings, color="red")
            old_provider = GatedCroppingProvider()
            old_service = OCRService(old_provider, settings)
            old_request = asyncio.create_task(
                old_service.recognize(
                    old_session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="old-worker-late-success",
                )
            )
            await asyncio.wait_for(old_provider.started.wait(), timeout=2)

            async with factory() as session:
                task = await session.scalar(select(OCRTask))
                assert task is not None
                old_claim_token = task.provider_request_id
                await session.execute(
                    update(OCRTask)
                    .where(OCRTask.id == task.id)
                    .values(
                        updated_at=datetime.now(timezone.utc)
                        - timedelta(seconds=settings.ocr_processing_lease_seconds + 1)
                    )
                )
                await session.commit()

            new_service = OCRService(FakeProvider(), settings)
            raw = (settings.upload_dir / source.storage_name).read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            key = new_service._idempotency_key(
                user_id=user_id,
                source_hash=source_hash,
                pdf_page_number=1,
            )
            async with factory() as session:
                new_claim = await new_service._claim_task(
                    session,
                    user_id=user_id,
                    asset=source,
                    source_hash=source_hash,
                    pdf_page_number=1,
                    idempotency_key=key,
                )
                assert new_claim.owner_token is not None
                assert new_claim.owner_token != old_claim_token
                await new_service._cancel_owned_claim(
                    session,
                    idempotency_key=key,
                    claim_token=new_claim.owner_token,
                )

            old_provider.release.set()
            with pytest.raises(APIError) as caught:
                await old_request
            assert caught.value.code == "OCR_IN_PROGRESS"

            async with factory() as session:
                persisted = await session.scalar(select(OCRTask))
                assets = (
                    await session.scalars(
                        select(UploadedAsset).where(UploadedAsset.user_id == user_id)
                    )
                ).all()
            assert persisted is not None
            assert persisted.status == "failed"
            assert persisted.provider_request_id is None
            assert persisted.error_code == "OCR_CANCELLED"
            assert [asset.id for asset in assets] == [source.id]
            assert sorted(path.name for path in settings.upload_dir.iterdir()) == [
                source.storage_name
            ]
        finally:
            old_provider.release.set()
            if not old_request.done():
                old_request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await old_request
            await old_session.close()
            await engine.dispose()

    asyncio.run(scenario())


def test_late_failure_cannot_overwrite_reclaimed_processing_claim(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        old_session = factory()
        try:
            user_id, source = await _source_asset(factory, settings)
            old_provider = GatedFailingProvider()
            old_service = OCRService(old_provider, settings)
            old_request = asyncio.create_task(
                old_service.recognize(
                    old_session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="old-worker-late-failure",
                )
            )
            await asyncio.wait_for(old_provider.started.wait(), timeout=2)

            async with factory() as session:
                task = await session.scalar(select(OCRTask))
                assert task is not None
                old_claim_token = task.provider_request_id
                await session.execute(
                    update(OCRTask)
                    .where(OCRTask.id == task.id)
                    .values(
                        updated_at=datetime.now(timezone.utc)
                        - timedelta(seconds=settings.ocr_processing_lease_seconds + 1)
                    )
                )
                await session.commit()

            new_service = OCRService(FakeProvider(), settings)
            raw = (settings.upload_dir / source.storage_name).read_bytes()
            source_hash = hashlib.sha256(raw).hexdigest()
            key = new_service._idempotency_key(
                user_id=user_id,
                source_hash=source_hash,
                pdf_page_number=1,
            )
            async with factory() as session:
                new_claim = await new_service._claim_task(
                    session,
                    user_id=user_id,
                    asset=source,
                    source_hash=source_hash,
                    pdf_page_number=1,
                    idempotency_key=key,
                )
            assert new_claim.owner_token is not None
            assert new_claim.owner_token != old_claim_token

            old_provider.release.set()
            with pytest.raises(APIError) as caught:
                await old_request
            assert caught.value.code == "OCR_PROVIDER_ERROR"

            async with factory() as session:
                persisted = await session.scalar(select(OCRTask))
            assert persisted is not None
            assert persisted.status == "processing"
            assert persisted.provider_request_id == new_claim.owner_token
            assert persisted.error_code is None
        finally:
            old_provider.release.set()
            if not old_request.done():
                old_request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await old_request
            await old_session.close()
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("existing_failed", "target_commit"),
    [(False, 2), (True, 1)],
    ids=["new-insert", "failed-cas"],
)
def test_cancelled_claim_commit_does_not_leave_processing_task(
    existing_failed, target_commit, tmp_path
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            if existing_failed:
                await _seed_failed_ocr_task(factory, service, user_id, source)

            async with factory() as real_session:
                wrapped = ClaimCommitSession(
                    real_session,
                    target_commit=target_commit,
                    block_after_commit=True,
                )
                pending = asyncio.create_task(
                    service.recognize(
                        wrapped,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="cancelled-claim",
                    )
                )
                await asyncio.wait_for(wrapped.committed.wait(), timeout=2)
                pending.cancel()
                await asyncio.sleep(0)
                wrapped.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            assert provider.calls == 0
            async with factory() as check_session:
                task = await check_session.scalar(select(OCRTask))
            assert task is not None
            assert task.status == "failed"
            assert task.error_code == "OCR_CANCELLED"

            async with factory() as retry_session:
                result = await service.recognize(
                    retry_session,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="cancelled-claim-retry",
                )
            assert result.question_count == 1
            assert provider.calls == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("existing_failed", "target_commit", "late_error"),
    [
        (False, 2, "oserror"),
        (True, 1, "oserror"),
        (False, 2, "integrity"),
    ],
    ids=["new-insert-oserror", "failed-cas-oserror", "new-insert-integrity"],
)
def test_cancelled_claim_commit_late_error_preserves_cancellation(
    existing_failed, target_commit, late_error, tmp_path
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            if existing_failed:
                await _seed_failed_ocr_task(factory, service, user_id, source)
            exception = (
                IntegrityError("commit", {}, Exception("late integrity error"))
                if late_error == "integrity"
                else OSError("claim commit result unavailable")
            )

            async with factory() as real_session:
                wrapped = ClaimCommitSession(
                    real_session,
                    target_commit=target_commit,
                    block_after_commit=True,
                    late_exception=exception,
                )
                pending = asyncio.create_task(
                    service.recognize(
                        wrapped,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="cancelled-late-claim-error",
                    )
                )
                await asyncio.wait_for(wrapped.committed.wait(), timeout=2)
                pending.cancel()
                await asyncio.sleep(0)
                wrapped.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            assert provider.calls == 0
            async with factory() as check_session:
                task = await check_session.scalar(select(OCRTask))
            assert task is not None
            assert task.status == "failed"
            assert task.error_code == "OCR_CANCELLED"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_cancelled_late_noop_claim_error_does_not_modify_other_owner(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            seeded = await _seed_failed_ocr_task(factory, service, user_id, source)
            async with factory() as session:
                task = await session.get(OCRTask, seeded.id)
                assert task is not None
                task.status = "processing"
                task.provider_request_id = "other-owner-token"
                task.error_code = None
                task.error_message = None
                await session.commit()

            async with factory() as real_session:
                wrapped = ClaimCommitSession(
                    real_session,
                    target_commit=1,
                    block_after_commit=True,
                    late_exception=OSError("claim commit result unavailable"),
                )
                pending = asyncio.create_task(
                    service.recognize(
                        wrapped,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="cancelled-other-owner-claim",
                    )
                )
                await asyncio.wait_for(wrapped.committed.wait(), timeout=2)
                pending.cancel()
                await asyncio.sleep(0)
                wrapped.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            assert provider.calls == 0
            async with factory() as check_session:
                task = await check_session.get(OCRTask, seeded.id)
            assert task is not None
            assert task.status == "processing"
            assert task.provider_request_id == "other-owner-token"
            assert task.error_code is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "claim_path",
    ["failed-cas", "new-insert-oserror", "new-insert-integrity"],
)
def test_cancelled_owned_claim_lookup_marks_task_failed(claim_path, tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            if claim_path == "failed-cas":
                await _seed_failed_ocr_task(factory, service, user_id, source)

            async with factory() as real_session:
                claim_session = real_session
                target_scalar = 1
                if claim_path != "failed-cas":
                    exception = (
                        IntegrityError(
                            "commit",
                            {},
                            Exception("late integrity error"),
                        )
                        if claim_path == "new-insert-integrity"
                        else OSError("claim commit result unavailable")
                    )
                    claim_session = ClaimCommitSession(
                        real_session,
                        target_commit=2,
                        late_exception=exception,
                    )
                    target_scalar = 2
                wrapped = BlockScalarAfterReadSession(
                    claim_session,
                    target_scalar=target_scalar,
                )
                pending = asyncio.create_task(
                    service.recognize(
                        wrapped,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="cancelled-owned-claim-lookup",
                    )
                )
                await asyncio.wait_for(wrapped.read.wait(), timeout=2)
                pending.cancel()
                await asyncio.sleep(0)
                wrapped.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            assert provider.calls == 0
            async with factory() as check_session:
                task = await check_session.scalar(select(OCRTask))
            assert task is not None
            assert task.status == "failed"
            assert task.provider_request_id is None
            assert task.error_code == "OCR_CANCELLED"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_cancelled_claim_lookup_does_not_modify_other_owner(tmp_path):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            seeded = await _seed_failed_ocr_task(factory, service, user_id, source)
            async with factory() as session:
                task = await session.get(OCRTask, seeded.id)
                assert task is not None
                task.status = "processing"
                task.provider_request_id = "other-owner-token"
                task.error_code = None
                task.error_message = None
                await session.commit()

            async with factory() as real_session:
                wrapped = BlockScalarAfterReadSession(
                    real_session,
                    target_scalar=1,
                )
                pending = asyncio.create_task(
                    service.recognize(
                        wrapped,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="cancelled-other-owner-lookup",
                    )
                )
                await asyncio.wait_for(wrapped.read.wait(), timeout=2)
                pending.cancel()
                await asyncio.sleep(0)
                wrapped.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await pending

            assert provider.calls == 0
            async with factory() as check_session:
                task = await check_session.get(OCRTask, seeded.id)
            assert task is not None
            assert task.status == "processing"
            assert task.provider_request_id == "other-owner-token"
            assert task.error_code is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("existing_failed", "target_commit"),
    [(False, 2), (True, 1)],
    ids=["new-insert", "failed-cas"],
)
def test_ambiguous_successful_claim_commit_continues_without_stuck_processing(
    existing_failed, target_commit, tmp_path
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            if existing_failed:
                await _seed_failed_ocr_task(factory, service, user_id, source)

            async with factory() as real_session:
                wrapped = ClaimCommitSession(
                    real_session,
                    target_commit=target_commit,
                    raise_after_commit=True,
                )
                result = await service.recognize(
                    wrapped,
                    user_id=user_id,
                    asset=source,
                    pdf_page_number=1,
                    local_request_id="ambiguous-claim",
                )

            assert result.question_count == 1
            assert provider.calls == 1
            async with factory() as check_session:
                task = await check_session.scalar(select(OCRTask))
            assert task is not None
            assert task.status == "succeeded"
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_ambiguous_noop_claim_does_not_modify_another_instances_processing_task(
    tmp_path,
):
    async def scenario():
        settings, engine, factory = await _database(tmp_path)
        try:
            user_id, source = await _source_asset(factory, settings)
            provider = FakeProvider()
            service = OCRService(provider, settings)
            seeded = await _seed_failed_ocr_task(factory, service, user_id, source)
            async with factory() as session:
                task = await session.get(OCRTask, seeded.id)
                assert task is not None
                task.status = "processing"
                task.error_code = None
                task.error_message = None
                await session.commit()

            async with factory() as real_session:
                wrapped = ClaimCommitSession(
                    real_session,
                    target_commit=1,
                    raise_after_commit=True,
                )
                with pytest.raises(APIError) as caught:
                    await service.recognize(
                        wrapped,
                        user_id=user_id,
                        asset=source,
                        pdf_page_number=1,
                        local_request_id="other-instance-processing",
                    )
            assert caught.value.code == "OCR_IN_PROGRESS"
            assert provider.calls == 0
            async with factory() as check_session:
                task = await check_session.get(OCRTask, seeded.id)
            assert task is not None
            assert task.status == "processing"
            assert task.error_code is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())
