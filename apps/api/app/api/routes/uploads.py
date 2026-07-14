from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.async_tasks import await_task_outcome
from app.core.database import get_session
from app.core.errors import APIError
from app.models.upload import UploadedAsset
from app.schemas.upload import UploadRead
from app.services.storage import (
    EmptyFile,
    EmptyFilename,
    InvalidImage,
    InvalidPdf,
    InvalidFilename,
    FilenameTooLong,
    UnsupportedImageType,
    UploadTooLarge,
    image_path,
    save_image,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])
Session = Annotated[AsyncSession, Depends(get_session)]


async def _finish_failed_upload(
    session: AsyncSession,
    *,
    upload_dir: Path,
    storage_name: str,
) -> BaseException | None:
    cleanup = asyncio.create_task(
        asyncio.to_thread(
            image_path(upload_dir, storage_name).unlink,
            missing_ok=True,
        )
    )
    cleanup_outcome = await await_task_outcome(cleanup)

    rollback = asyncio.create_task(session.rollback())
    rollback_outcome = await await_task_outcome(rollback)
    return cleanup_outcome.error or rollback_outcome.error


@router.post(
    "/questions", response_model=UploadRead, status_code=status.HTTP_201_CREATED
)
async def upload_question_image(
    file: Annotated[UploadFile, File(...)],
    current_user: CurrentUser,
    session: Session,
    request: Request,
) -> UploadRead:
    settings = request.app.state.settings
    if not request.app.state.upload_rate_limiter.allow(current_user.id):
        raise APIError(
            429,
            "UPLOAD_RATE_LIMITED",
            "上传请求过于频繁，请稍后再试",
        )

    try:
        await asyncio.wait_for(
            request.app.state.upload_semaphore.acquire(),
            timeout=settings.upload_queue_timeout_seconds,
        )
    except TimeoutError as exc:
        raise APIError(
            429,
            "UPLOAD_RATE_LIMITED",
            "上传服务繁忙，请稍后重试",
        ) from exc
    try:
        try:
            stored = await save_image(
                file,
                upload_dir=settings.upload_dir,
                max_upload_bytes=settings.max_upload_bytes,
            )
        finally:
            request.app.state.upload_semaphore.release()
    except UnsupportedImageType as exc:
        raise APIError(
            422,
            "OCR_UNSUPPORTED_FILE_TYPE",
            "仅支持 JPEG、PNG、BMP 图片或 PDF 文件",
        ) from exc
    except InvalidImage as exc:
        raise APIError(
            422, "OCR_IMAGE_DECODE_FAILED", "图片文件损坏或无法解析"
        ) from exc
    except InvalidPdf as exc:
        raise APIError(422, "OCR_INVALID_PDF", "PDF 文件损坏或无法解析") from exc
    except EmptyFile as exc:
        raise APIError(422, "OCR_EMPTY_FILE", "上传文件不能为空") from exc
    except UploadTooLarge as exc:
        raise APIError(413, "OCR_FILE_TOO_LARGE", "文件大小超过限制") from exc
    except FilenameTooLong as exc:
        raise APIError(400, "filename_too_long", "文件名过长") from exc
    except EmptyFilename as exc:
        raise APIError(422, "OCR_INVALID_FILENAME", "文件名不能为空") from exc
    except InvalidFilename as exc:
        raise APIError(400, "filename_invalid", "文件名包含非法字符") from exc

    asset = UploadedAsset(
        user_id=current_user.id,
        storage_name=stored.storage_name,
        original_name=stored.original_name,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
    )
    session.add(asset)
    commit = asyncio.create_task(session.commit())
    commit_outcome = await await_task_outcome(commit)
    if commit_outcome.error is not None:
        cleanup_error = await _finish_failed_upload(
            session,
            upload_dir=settings.upload_dir,
            storage_name=stored.storage_name,
        )
        if cleanup_error is not None and not commit_outcome.caller_cancelled:
            raise cleanup_error
        if commit_outcome.caller_cancelled:
            raise asyncio.CancelledError from commit_outcome.error
        raise commit_outcome.error
    if commit_outcome.caller_cancelled:
        # A successful commit owns both the row and file.  Keep that consistent
        # state even though the disconnected caller will not receive the ID.
        raise asyncio.CancelledError
    await session.refresh(asset)
    return UploadRead(
        id=asset.id,
        original_name=asset.original_name,
        storage_name=asset.storage_name,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        created_at=asset.created_at,
        file_kind=stored.file_kind,
        width=stored.width,
        height=stored.height,
        page_count=stored.page_count,
        warnings=list(stored.warnings),
    )


@router.get("/{asset_id}")
async def download_upload(
    asset_id: str, current_user: CurrentUser, session: Session, request: Request
) -> FileResponse:
    asset = await session.scalar(
        select(UploadedAsset).where(
            UploadedAsset.id == asset_id, UploadedAsset.user_id == current_user.id
        )
    )
    if asset is None:
        raise APIError(404, "not_found", "上传文件不存在")
    try:
        path = image_path(request.app.state.settings.upload_dir, asset.storage_name)
    except ValueError as exc:
        raise APIError(404, "not_found", "上传文件不存在") from exc
    if not path.is_file():
        raise APIError(404, "not_found", "上传文件不存在")
    return FileResponse(path, media_type=asset.mime_type, filename=asset.original_name)
