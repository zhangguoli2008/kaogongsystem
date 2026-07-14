"""Persistent orchestration for question-split OCR requests."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import logging
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import AsyncIterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import APIError
from app.core.rate_limit import DualWindowRateLimiter
from app.models.ocr_task import OCRTask
from app.models.upload import UploadedAsset
from app.schemas.ocr import OcrResult
from app.services.ocr.base import OCRProvider
from app.services.ocr.cropper import CropArtifact, build_crop_batch
from app.services.ocr.errors import OCRProviderError, map_provider_exception
from app.services.ocr.normalizer import (
    NoQuestionDetected,
    normalize_question_split_response,
)
from app.services.ocr_contract import API_NAME
from app.services.storage import (
    EmptyFile,
    InvalidImage,
    InvalidPdf,
    UnsupportedImageType,
    image_path,
    inspect_file,
    save_generated_png,
)


logger = logging.getLogger(__name__)
PARAMETER_VERSION = "question-split-v1"


class _LockEntry:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.references = 0


class _KeyedLocks:
    """Reference-counted locks shared by all service instances in this process."""

    _entries: dict[str, _LockEntry] = {}
    _guard = Lock()

    @classmethod
    @asynccontextmanager
    async def hold(cls, key: str) -> AsyncIterator[None]:
        with cls._guard:
            entry = cls._entries.get(key)
            if entry is None:
                entry = _LockEntry()
                cls._entries[key] = entry
            entry.references += 1
        try:
            await entry.lock.acquire()
            try:
                yield
            finally:
                entry.lock.release()
        finally:
            with cls._guard:
                entry.references -= 1
                if entry.references == 0:
                    cls._entries.pop(key, None)


class OCRService:
    def __init__(
        self,
        provider: OCRProvider,
        settings: Settings,
        *,
        rate_limiter: DualWindowRateLimiter | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._rate_limiter = rate_limiter or DualWindowRateLimiter(
            minute_limit=settings.ocr_rate_limit_per_minute,
            hour_limit=settings.ocr_rate_limit_per_hour,
        )
        self._semaphore = asyncio.Semaphore(
            settings.tencentcloud_ocr_max_concurrency
        )

    async def recognize(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        asset: UploadedAsset,
        pdf_page_number: int,
        local_request_id: str,
    ) -> OcrResult:
        started = monotonic()
        if asset.user_id != user_id:
            raise APIError(404, "OCR_SOURCE_NOT_FOUND", "未找到上传文件")

        raw, inspection = await asyncio.to_thread(self._read_and_inspect, asset)
        if pdf_page_number < 1 or (
            inspection.file_kind == "pdf"
            and (
                inspection.page_count is None
                or pdf_page_number > inspection.page_count
            )
        ):
            raise APIError(422, "OCR_INVALID_PDF_PAGE", "PDF 页码无效")

        source_hash = hashlib.sha256(raw).hexdigest()
        idempotency_key = self._idempotency_key(
            user_id=user_id,
            source_hash=source_hash,
            pdf_page_number=pdf_page_number,
        )
        async with _KeyedLocks.hold(idempotency_key):
            task, cached = await self._claim_task(
                session,
                user_id=user_id,
                asset=asset,
                source_hash=source_hash,
                pdf_page_number=pdf_page_number,
                idempotency_key=idempotency_key,
            )
            if cached is not None:
                return cached

            acquired = False
            generated_storage_names: list[str] = []
            provider_request_id: str | None = None
            try:
                try:
                    await asyncio.wait_for(
                        self._semaphore.acquire(),
                        timeout=self._settings.tencentcloud_ocr_queue_timeout_seconds,
                    )
                    acquired = True
                except TimeoutError:
                    raise APIError(
                        429,
                        "OCR_RATE_LIMITED",
                        "OCR 服务繁忙，请稍后重试",
                    ) from None

                if not self._rate_limiter.allow(user_id):
                    raise APIError(429, "OCR_RATE_LIMITED", "OCR 请求过于频繁")

                try:
                    raw_response = await self._provider.recognize_questions(
                        raw,
                        asset.original_name,
                        inspection.mime_type,
                        pdf_page_number,
                    )
                finally:
                    self._semaphore.release()
                    acquired = False
                provider_request_id = raw_response.request_id
                result = normalize_question_split_response(
                    raw_response,
                    provider=self._provider.name,
                    file_id=asset.id,
                    page_number=pdf_page_number,
                    is_demo=self._provider.is_demo,
                )
                result.warnings = [*inspection.warnings, *result.warnings]
                crop_batch = await asyncio.to_thread(
                    build_crop_batch,
                    raw_response,
                    result,
                    source_raw=raw,
                    source_file_kind=inspection.file_kind,
                )
                result.warnings.extend(crop_batch.warnings)
                await self._persist_crops(
                    session,
                    user_id=user_id,
                    result=result,
                    artifacts=crop_batch.artifacts,
                    generated_storage_names=generated_storage_names,
                )
                task.status = "succeeded"
                task.question_count = result.question_count
                task.provider_request_id = result.request_id
                task.normalized_result_json = result.model_dump(mode="json")
                task.error_code = None
                task.error_message = None
                await session.commit()
                self._log_completion(
                    local_request_id=local_request_id,
                    user_id=user_id,
                    provider_request_id=result.request_id,
                    duration=monotonic() - started,
                    success=True,
                    count=result.question_count,
                    error_code=None,
                    file_size=len(raw),
                    page=pdf_page_number,
                )
                return result
            except asyncio.CancelledError:
                error = APIError(499, "OCR_CANCELLED", "OCR 请求已取消")
                await asyncio.shield(
                    self._mark_failed(
                        session,
                        task.id,
                        error,
                        generated_storage_names=generated_storage_names,
                    )
                )
                raise
            except Exception as exc:
                error = self._safe_error(exc)
                await self._mark_failed(
                    session,
                    task.id,
                    error,
                    generated_storage_names=generated_storage_names,
                )
                self._log_completion(
                    local_request_id=local_request_id,
                    user_id=user_id,
                    provider_request_id=provider_request_id,
                    duration=monotonic() - started,
                    success=False,
                    count=0,
                    error_code=error.code,
                    file_size=len(raw),
                    page=pdf_page_number,
                )
                if isinstance(exc, APIError):
                    raise
                raise error from None
            finally:
                if acquired:
                    self._semaphore.release()

    def _read_and_inspect(self, asset: UploadedAsset):
        path = image_path(self._settings.upload_dir, asset.storage_name)
        try:
            raw = Path(path).read_bytes()
        except (FileNotFoundError, OSError) as exc:
            raise APIError(404, "OCR_SOURCE_NOT_FOUND", "未找到上传文件") from exc
        if len(base64.b64encode(raw)) > self._settings.max_upload_bytes:
            raise APIError(413, "OCR_FILE_TOO_LARGE", "上传文件过大")
        try:
            return raw, inspect_file(raw)
        except EmptyFile as exc:
            raise APIError(422, "OCR_IMAGE_DECODE_FAILED", "无法解析上传文件") from exc
        except (InvalidImage, InvalidPdf, UnsupportedImageType) as exc:
            raise APIError(422, "OCR_IMAGE_DECODE_FAILED", "无法解析上传文件") from exc

    def _idempotency_key(
        self,
        *,
        user_id: str,
        source_hash: str,
        pdf_page_number: int,
    ) -> str:
        material = "\x1f".join(
            (
                user_id,
                source_hash,
                str(pdf_page_number),
                self._provider.name,
                PARAMETER_VERSION,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    async def _claim_task(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        asset: UploadedAsset,
        source_hash: str,
        pdf_page_number: int,
        idempotency_key: str,
    ) -> tuple[OCRTask, OcrResult | None]:
        task = await session.scalar(
            select(OCRTask).where(OCRTask.idempotency_key == idempotency_key)
        )
        if task is not None:
            if task.status == "succeeded" and task.normalized_result_json is not None:
                return task, OcrResult.model_validate(task.normalized_result_json)
            if task.status == "processing":
                raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")
            task.status = "processing"
            task.error_code = None
            task.error_message = None
            await session.commit()
            return task, None

        task = OCRTask(
            user_id=user_id,
            source_file_id=asset.id,
            provider=self._provider.name,
            api_name=API_NAME,
            source_file_hash=source_hash,
            pdf_page_number=pdf_page_number,
            parameter_version=PARAMETER_VERSION,
            idempotency_key=idempotency_key,
            status="processing",
        )
        session.add(task)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(
                select(OCRTask).where(OCRTask.idempotency_key == idempotency_key)
            )
            if existing is None:
                raise
            if (
                existing.status == "succeeded"
                and existing.normalized_result_json is not None
            ):
                return existing, OcrResult.model_validate(
                    existing.normalized_result_json
                )
            if existing.status == "processing":
                raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")
            existing.status = "processing"
            existing.error_code = None
            existing.error_message = None
            await session.commit()
            return existing, None
        return task, None

    async def _persist_crops(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        result: OcrResult,
        artifacts: tuple[CropArtifact, ...],
        generated_storage_names: list[str],
    ) -> None:
        for artifact in artifacts:
            stored = await asyncio.to_thread(
                save_generated_png,
                artifact.png_bytes,
                upload_dir=self._settings.upload_dir,
                original_name=artifact.original_name,
            )
            generated_storage_names.append(stored.storage_name)
            asset_id = str(uuid4())
            session.add(
                UploadedAsset(
                    id=asset_id,
                    user_id=user_id,
                    storage_name=stored.storage_name,
                    original_name=stored.original_name,
                    mime_type="image/png",
                    size_bytes=stored.size_bytes,
                )
            )
            self._attach_crop(result, artifact, asset_id)

    @staticmethod
    def _attach_crop(
        result: OcrResult,
        artifact: CropArtifact,
        asset_id: str,
    ) -> None:
        question = result.questions[artifact.question_position]
        image_url = f"/uploads/{asset_id}"
        if artifact.kind == "question":
            question.crop_asset_id = asset_id
            question.crop_image_url = image_url
            return
        if artifact.item_position is None:
            raise ValueError("crop item position is required")
        if artifact.kind == "figure":
            item = question.figures[artifact.item_position]
        elif artifact.kind == "table":
            item = question.tables[artifact.item_position]
        else:
            item = question.options[artifact.item_position]
        item.asset_id = asset_id
        item.image_url = image_url

    @staticmethod
    def _safe_error(exc: Exception) -> APIError:
        if isinstance(exc, APIError):
            return exc
        if isinstance(exc, NoQuestionDetected):
            return APIError(422, "OCR_NO_QUESTION_DETECTED", "未识别到有效题目")
        if isinstance(exc, OCRProviderError):
            mapped = map_provider_exception(exc)
            return APIError(mapped.status_code, mapped.code, mapped.message)
        return APIError(500, "OCR_PROCESSING_FAILED", "OCR 结果处理失败")

    async def _mark_failed(
        self,
        session: AsyncSession,
        task_id: str,
        error: APIError,
        *,
        generated_storage_names: list[str],
    ) -> None:
        await session.rollback()
        for storage_name in generated_storage_names:
            try:
                await asyncio.to_thread(
                    image_path(self._settings.upload_dir, storage_name).unlink,
                    missing_ok=True,
                )
            except OSError:
                logger.error("Failed to remove OCR generated asset")
        task = await session.get(OCRTask, task_id)
        if task is None:
            return
        task.status = "failed"
        task.question_count = 0
        task.normalized_result_json = None
        task.error_code = error.code
        task.error_message = error.message
        await session.commit()

    def _log_completion(
        self,
        *,
        local_request_id: str,
        user_id: str,
        provider_request_id: str | None,
        duration: float,
        success: bool,
        count: int,
        error_code: str | None,
        file_size: int,
        page: int,
    ) -> None:
        logger.info(
            "OCR request completed",
            extra={
                "local_request_id": local_request_id,
                "user_id": user_id,
                "provider": self._provider.name,
                "api_name": API_NAME,
                "provider_request_id": provider_request_id,
                "duration_seconds": duration,
                "success": success,
                "question_count": count,
                "error_code": error_code,
                "file_size": file_size,
                "page": page,
            },
        )
