from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
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
    try:
        stored = await save_image(
            file,
            upload_dir=settings.upload_dir,
            max_upload_bytes=settings.max_upload_bytes,
        )
    except UnsupportedImageType as exc:
        raise APIError(
            422,
            "OCR_UNSUPPORTED_FILE_TYPE",
            "仅支持 JPEG、PNG、BMP 图片或 PDF 文件",
        ) from exc
    except InvalidImage as exc:
        raise APIError(422, "OCR_IMAGE_DECODE_FAILED", "图片文件损坏或无法解析") from exc
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
    try:
        await session.commit()
    except Exception:
        image_path(settings.upload_dir, stored.storage_name).unlink(missing_ok=True)
        await session.rollback()
        raise
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
