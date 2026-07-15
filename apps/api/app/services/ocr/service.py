"""Persistent orchestration for question-split OCR requests."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, AsyncIterator, TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from app.core.async_tasks import await_task_outcome
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
    FileInspection,
    InvalidImage,
    InvalidPdf,
    UnsupportedImageType,
    image_path,
    inspect_file,
    save_generated_png,
)


logger = logging.getLogger(__name__)
PARAMETER_VERSION = "question-split-v1"
_TaskResult = TypeVar("_TaskResult")


async def _await_task_completion(
    task: asyncio.Task[_TaskResult],
) -> tuple[_TaskResult, bool]:
    """Wait for a side effect to finish without abandoning it on cancellation."""

    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


@dataclass(frozen=True)
class _ClaimOperationOutcome:
    value: bool | None
    error: BaseException | None
    cancelled: bool


async def _await_claim_operation(
    task: asyncio.Task[bool | None],
) -> _ClaimOperationOutcome:
    """Wait for a claim side effect while preserving cancellation and errors."""

    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                cancelled = True
        except Exception:
            # The background error remains available through task.result().
            pass
    try:
        value = task.result()
    except (Exception, asyncio.CancelledError) as error:
        return _ClaimOperationOutcome(None, error, cancelled)
    return _ClaimOperationOutcome(value, None, cancelled)


def _claimable_task_statement(
    idempotency_key: str,
    claim_token: str,
    stale_before: datetime,
) -> Update:
    return (
        update(OCRTask)
        .where(
            OCRTask.idempotency_key == idempotency_key,
            or_(
                OCRTask.status == "failed",
                and_(
                    OCRTask.status == "processing",
                    OCRTask.updated_at <= stale_before,
                ),
            ),
        )
        .values(
            status="processing",
            provider_request_id=claim_token,
            error_code=None,
            error_message=None,
        )
    )


@dataclass(frozen=True)
class _TaskClaim:
    task: OCRTask
    cached: OcrResult | None
    owner_token: str | None
    cancelled: bool = False


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
        self._semaphore = asyncio.Semaphore(settings.tencentcloud_ocr_max_concurrency)

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
        if inspection.file_kind == "pdf":
            if (
                pdf_page_number < 1
                or inspection.page_count is None
                or pdf_page_number > inspection.page_count
            ):
                raise APIError(422, "OCR_INVALID_PDF_PAGE", "PDF 页码无效")
            effective_page_number = pdf_page_number
        else:
            effective_page_number = 1

        source_hash = hashlib.sha256(raw).hexdigest()
        idempotency_key = self._idempotency_key(
            user_id=user_id,
            source_hash=source_hash,
            pdf_page_number=effective_page_number,
        )
        async with _KeyedLocks.hold(idempotency_key):
            claim = await self._claim_task(
                session,
                user_id=user_id,
                asset=asset,
                source_hash=source_hash,
                pdf_page_number=effective_page_number,
                idempotency_key=idempotency_key,
            )
            task = claim.task
            if claim.cancelled:
                if claim.owner_token is not None:
                    await self._cancel_owned_claim(
                        session,
                        idempotency_key=task.idempotency_key,
                        claim_token=claim.owner_token,
                    )
                self._log_completion(
                    local_request_id=local_request_id,
                    user_id=user_id,
                    provider_request_id=None,
                    duration=monotonic() - started,
                    success=False,
                    count=0,
                    error_code="OCR_CANCELLED",
                    file_size=len(raw),
                    page=effective_page_number,
                )
                raise asyncio.CancelledError
            if claim.cached is not None:
                return claim.cached

            acquired = False
            generated_assets: list[tuple[str, str]] = []
            provider_request_id: str | None = None
            success_cas_applied = False
            success_committed = False
            claim_token = claim.owner_token
            if claim_token is None:
                raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")
            try:
                if not getattr(self._provider, "is_configured", True):
                    raise APIError(503, "OCR_NOT_CONFIGURED", "OCR 服务未配置")

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

                raw_response = await self._provider.recognize_questions(
                    raw,
                    asset.original_name,
                    inspection.mime_type,
                    effective_page_number,
                )
                provider_request_id = raw_response.request_id
                result = normalize_question_split_response(
                    raw_response,
                    provider=self._provider.name,
                    file_id=asset.id,
                    page_number=effective_page_number,
                    is_demo=self._provider.is_demo,
                )
                result.warnings = [*inspection.warnings, *result.warnings]
                crop_task = asyncio.create_task(
                    asyncio.to_thread(
                        build_crop_batch,
                        raw_response,
                        result,
                        source_raw=raw,
                        source_file_kind=inspection.file_kind,
                        max_corrected_image_bytes=(
                            self._settings.ocr_corrected_image_max_bytes
                        ),
                        max_corrected_images_total_bytes=(
                            self._settings.ocr_corrected_images_max_total_bytes
                        ),
                        max_artifacts=self._settings.ocr_crop_max_artifacts,
                        max_total_png_bytes=(
                            self._settings.ocr_crop_max_total_png_bytes
                        ),
                    )
                )
                crop_outcome = await await_task_outcome(crop_task)
                if crop_outcome.error is not None:
                    if crop_outcome.caller_cancelled:
                        raise asyncio.CancelledError from crop_outcome.error
                    raise crop_outcome.error
                if crop_outcome.caller_cancelled:
                    raise asyncio.CancelledError
                if crop_outcome.value is None:
                    raise RuntimeError("crop worker returned no result")
                crop_batch = crop_outcome.value
                result.warnings.extend(crop_batch.warnings)
                await self._persist_crops(
                    session,
                    user_id=user_id,
                    result=result,
                    artifacts=crop_batch.artifacts,
                    generated_assets=generated_assets,
                )
                success_update = cast(
                    CursorResult[Any],
                    await session.execute(
                        update(OCRTask)
                        .where(
                            OCRTask.id == task.id,
                            OCRTask.status == "processing",
                            OCRTask.provider_request_id == claim_token,
                        )
                        .values(
                            status="succeeded",
                            question_count=result.question_count,
                            provider_request_id=result.request_id,
                            normalized_result_json=result.model_dump(mode="json"),
                            error_code=None,
                            error_message=None,
                        ),
                        execution_options={"synchronize_session": False},
                    ),
                )
                if success_update.rowcount != 1:
                    raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")
                success_cas_applied = True
                commit_task = asyncio.create_task(session.commit())
                _, cancelled_during_commit = await _await_task_completion(commit_task)
                success_committed = True
                self._log_completion(
                    local_request_id=local_request_id,
                    user_id=user_id,
                    provider_request_id=result.request_id,
                    duration=monotonic() - started,
                    success=True,
                    count=result.question_count,
                    error_code=None,
                    file_size=len(raw),
                    page=effective_page_number,
                )
                if cancelled_during_commit:
                    raise asyncio.CancelledError
                return result
            except asyncio.CancelledError:
                if success_committed:
                    raise
                error = APIError(499, "OCR_CANCELLED", "OCR 请求已取消")
                failed_task = asyncio.create_task(
                    self._mark_failed(
                        session,
                        task.id,
                        claim_token,
                        error,
                        generated_assets=generated_assets,
                        provider_request_id=self._safe_provider_request_id(
                            provider_request_id
                        ),
                        preserve_committed_success=success_cas_applied,
                    )
                )
                failed_outcome = await await_task_outcome(failed_task)
                if failed_outcome.error is not None:
                    logger.error(
                        "Failed to finalize cancelled OCR task",
                        exc_info=failed_outcome.error,
                    )
                self._log_completion(
                    local_request_id=local_request_id,
                    user_id=user_id,
                    provider_request_id=self._safe_provider_request_id(
                        provider_request_id
                    ),
                    duration=monotonic() - started,
                    success=False,
                    count=0,
                    error_code=error.code,
                    file_size=len(raw),
                    page=effective_page_number,
                )
                raise
            except Exception as exc:
                if isinstance(exc, OCRProviderError):
                    provider_request_id = exc.request_id
                provider_request_id = self._safe_provider_request_id(
                    provider_request_id
                )
                error = self._safe_error(exc)
                failed_task = asyncio.create_task(
                    self._mark_failed(
                        session,
                        task.id,
                        claim_token,
                        error,
                        generated_assets=generated_assets,
                        provider_request_id=provider_request_id,
                        preserve_committed_success=success_cas_applied,
                    )
                )
                failed_outcome = await await_task_outcome(failed_task)
                if failed_outcome.error is not None:
                    if failed_outcome.caller_cancelled:
                        raise asyncio.CancelledError from failed_outcome.error
                    raise failed_outcome.error from exc
                self._log_completion(
                    local_request_id=local_request_id,
                    user_id=user_id,
                    provider_request_id=provider_request_id,
                    duration=monotonic() - started,
                    success=False,
                    count=0,
                    error_code=error.code,
                    file_size=len(raw),
                    page=effective_page_number,
                )
                if failed_outcome.caller_cancelled:
                    raise asyncio.CancelledError from exc
                if isinstance(exc, APIError):
                    raise
                raise error from None
            finally:
                if acquired:
                    self._semaphore.release()

    def _read_and_inspect(self, asset: UploadedAsset) -> tuple[bytes, FileInspection]:
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
    ) -> _TaskClaim:
        claim_token = str(uuid4())
        claimed, cancelled = await self._try_claim_task(
            session,
            idempotency_key,
            claim_token,
        )
        task = await self._task_for_key(
            session,
            idempotency_key,
            claim_token,
        )
        if task is None and cancelled:
            raise asyncio.CancelledError
        if task is not None:
            if claimed:
                return _TaskClaim(task, None, claim_token, cancelled)
            if cancelled:
                return _TaskClaim(task, None, None, True)
            if task.status == "succeeded" and task.normalized_result_json is not None:
                return _TaskClaim(
                    task,
                    OcrResult.model_validate(task.normalized_result_json),
                    None,
                )
            if task.status == "processing":
                raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")
            claimed, cancelled = await self._try_claim_task(
                session,
                idempotency_key,
                claim_token,
            )
            if claimed:
                refreshed = await self._task_for_key(
                    session,
                    idempotency_key,
                    claim_token,
                )
                if refreshed is not None:
                    return _TaskClaim(
                        refreshed,
                        None,
                        claim_token,
                        cancelled,
                    )
            if cancelled:
                refreshed = await self._task_for_key(
                    session,
                    idempotency_key,
                    claim_token,
                )
                if refreshed is not None:
                    return _TaskClaim(refreshed, None, None, True)
            raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")

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
            provider_request_id=claim_token,
        )
        session.add(task)
        commit_task = asyncio.create_task(session.commit())
        outcome = await _await_claim_operation(commit_task)
        if outcome.error is None:
            return _TaskClaim(task, None, claim_token, outcome.cancelled)

        await session.rollback()
        existing = await self._task_for_key(
            session,
            idempotency_key,
            claim_token,
        )
        if (
            existing is not None
            and existing.id == task.id
            and existing.status == "processing"
            and existing.provider_request_id == claim_token
        ):
            return _TaskClaim(
                existing,
                None,
                claim_token,
                outcome.cancelled,
            )
        if outcome.cancelled:
            if existing is not None:
                return _TaskClaim(existing, None, None, True)
            raise asyncio.CancelledError
        if not isinstance(outcome.error, IntegrityError):
            raise APIError(
                500,
                "OCR_PROCESSING_FAILED",
                "OCR 任务创建失败",
            ) from None

        claimed, cancelled = await self._try_claim_task(
            session,
            idempotency_key,
            claim_token,
        )
        existing = await self._task_for_key(
            session,
            idempotency_key,
            claim_token,
        )
        if existing is None:
            if cancelled:
                raise asyncio.CancelledError
            raise outcome.error
        if claimed:
            return _TaskClaim(existing, None, claim_token, cancelled)
        if cancelled:
            return _TaskClaim(existing, None, None, True)
        if (
            existing.status == "succeeded"
            and existing.normalized_result_json is not None
        ):
            return _TaskClaim(
                existing,
                OcrResult.model_validate(existing.normalized_result_json),
                None,
            )
        if existing.status == "processing":
            raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")
        claimed, cancelled = await self._try_claim_task(
            session,
            idempotency_key,
            claim_token,
        )
        if claimed:
            refreshed = await self._task_for_key(
                session,
                idempotency_key,
                claim_token,
            )
            if refreshed is not None:
                return _TaskClaim(
                    refreshed,
                    None,
                    claim_token,
                    cancelled,
                )
        if cancelled:
            refreshed = await self._task_for_key(
                session,
                idempotency_key,
                claim_token,
            )
            if refreshed is not None:
                return _TaskClaim(refreshed, None, None, True)
            raise asyncio.CancelledError
        raise APIError(409, "OCR_IN_PROGRESS", "OCR 任务正在处理中")

    @staticmethod
    async def _task_for_key(
        session: AsyncSession,
        idempotency_key: str,
        claim_token: str,
    ) -> OCRTask | None:
        try:
            return cast(
                OCRTask | None,
                await session.scalar(
                    select(OCRTask)
                    .where(OCRTask.idempotency_key == idempotency_key)
                    .execution_options(populate_existing=True)
                ),
            )
        except asyncio.CancelledError:
            await OCRService._cancel_owned_claim(
                session,
                idempotency_key=idempotency_key,
                claim_token=claim_token,
            )
            raise

    async def _try_claim_task(
        self,
        session: AsyncSession,
        idempotency_key: str,
        claim_token: str,
    ) -> tuple[bool, bool]:
        async def execute_and_commit() -> bool:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    _claimable_task_statement(
                        idempotency_key,
                        claim_token,
                        datetime.now(timezone.utc)
                        - timedelta(
                            seconds=self._settings.ocr_processing_lease_seconds
                        ),
                    ),
                    execution_options={"synchronize_session": False},
                ),
            )
            claimed = result.rowcount == 1
            await session.commit()
            return claimed

        operation = asyncio.create_task(execute_and_commit())
        outcome = await _await_claim_operation(operation)
        if outcome.error is None:
            return outcome.value is True, outcome.cancelled

        await session.rollback()
        existing = await OCRService._task_for_key(
            session,
            idempotency_key,
            claim_token,
        )
        if (
            existing is not None
            and existing.status == "processing"
            and existing.provider_request_id == claim_token
        ):
            return True, outcome.cancelled
        if existing is not None:
            return False, outcome.cancelled
        if outcome.cancelled:
            raise asyncio.CancelledError
        raise APIError(500, "OCR_PROCESSING_FAILED", "OCR 任务认领失败") from None

    @staticmethod
    async def _cancel_owned_claim(
        session: AsyncSession,
        *,
        idempotency_key: str,
        claim_token: str,
    ) -> None:
        await session.rollback()

        async def cancel_and_commit() -> None:
            await session.execute(
                update(OCRTask)
                .where(
                    OCRTask.idempotency_key == idempotency_key,
                    OCRTask.status == "processing",
                    OCRTask.provider_request_id == claim_token,
                )
                .values(
                    status="failed",
                    question_count=0,
                    provider_request_id=None,
                    normalized_result_json=None,
                    error_code="OCR_CANCELLED",
                    error_message="OCR 请求已取消",
                ),
                execution_options={"synchronize_session": False},
            )
            await session.commit()

        cancellation = asyncio.create_task(cancel_and_commit())
        await _await_task_completion(cancellation)

    async def _persist_crops(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        result: OcrResult,
        artifacts: tuple[CropArtifact, ...],
        generated_assets: list[tuple[str, str]],
    ) -> None:
        for artifact in artifacts:
            asset_id = str(uuid4())
            storage_name = f"{uuid4().hex}.png"
            generated_assets.append((asset_id, storage_name))
            write_task = asyncio.create_task(
                asyncio.to_thread(
                    save_generated_png,
                    artifact.png_bytes,
                    upload_dir=self._settings.upload_dir,
                    original_name=artifact.original_name,
                    storage_name=storage_name,
                )
            )
            stored, cancelled_during_write = await _await_task_completion(write_task)
            if cancelled_during_write:
                raise asyncio.CancelledError
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
            item.asset_id = asset_id
            item.image_url = image_url
        elif artifact.kind == "table":
            table = question.tables[artifact.item_position]
            table.asset_id = asset_id
            table.image_url = image_url
        else:
            option = question.options[artifact.item_position]
            option.asset_id = asset_id
            option.image_url = image_url

    @staticmethod
    def _safe_error(exc: Exception) -> APIError:
        if isinstance(exc, APIError):
            return exc
        if isinstance(exc, NoQuestionDetected):
            return APIError(422, "OCR_NO_QUESTION", "未识别到有效题目")
        if isinstance(exc, OCRProviderError):
            mapped = map_provider_exception(exc)
            return APIError(mapped.status_code, mapped.code, mapped.message)
        return APIError(500, "OCR_PROCESSING_FAILED", "OCR 结果处理失败")

    async def _mark_failed(
        self,
        session: AsyncSession,
        task_id: str,
        claim_token: str,
        error: APIError,
        *,
        generated_assets: list[tuple[str, str]],
        provider_request_id: str | None,
        preserve_committed_success: bool,
    ) -> None:
        preserve_assets = preserve_committed_success
        try:
            await session.rollback()
            task = await session.get(OCRTask, task_id, populate_existing=True)
            if (
                preserve_committed_success
                and task is not None
                and task.status == "succeeded"
                and task.normalized_result_json is not None
            ):
                # A commit can succeed server-side and still surface an I/O error to
                # the caller. In that ambiguous case the committed task and assets
                # are authoritative and must remain intact for the next retry.
                return
            preserve_assets = False
            if task is None:
                return
            failed_update = cast(
                CursorResult[Any],
                await session.execute(
                    update(OCRTask)
                    .where(
                        OCRTask.id == task_id,
                        OCRTask.status == "processing",
                        OCRTask.provider_request_id == claim_token,
                    )
                    .values(
                        status="failed",
                        question_count=0,
                        provider_request_id=provider_request_id,
                        normalized_result_json=None,
                        error_code=error.code,
                        error_message=error.message,
                    ),
                    execution_options={"synchronize_session": False},
                ),
            )
            if failed_update.rowcount == 1:
                await session.commit()
            else:
                await session.rollback()
        finally:
            if not preserve_assets:
                await self._remove_generated_assets(generated_assets)

    async def _remove_generated_assets(
        self,
        generated_assets: list[tuple[str, str]],
    ) -> None:
        for _, storage_name in generated_assets:
            try:
                cleanup = asyncio.create_task(
                    asyncio.to_thread(
                        image_path(self._settings.upload_dir, storage_name).unlink,
                        missing_ok=True,
                    )
                )
                outcome = await await_task_outcome(cleanup)
                if outcome.error is not None:
                    raise outcome.error
            except (OSError, ValueError):
                logger.error("Failed to remove OCR generated asset")

    @staticmethod
    def _safe_provider_request_id(value: str | None) -> str | None:
        if value is None or len(value) != 36:
            return None
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError):
            return None
        return str(parsed)

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
                "request_id": provider_request_id,
                "provider_request_id": provider_request_id,
                "duration_ms": int(max(0.0, duration) * 1000),
                "success": success,
                "question_count": count,
                "error_code": error_code,
                "file_size": file_size,
                "pdf_page_number": page,
            },
        )
