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
    InvalidImage,
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
) -> UploadedAsset:
    settings = request.app.state.settings
    try:
        storage_name, mime_type, original_name, size_bytes = await save_image(
            file,
            upload_dir=settings.upload_dir,
            max_upload_bytes=settings.max_upload_bytes,
        )
    except UnsupportedImageType as exc:
        raise APIError(415, "unsupported_image_type", "仅支持 JPEG、PNG 或 WebP 图片") from exc
    except InvalidImage as exc:
        raise APIError(400, "invalid_image", "图片文件损坏或无法解析") from exc
    except UploadTooLarge as exc:
        raise APIError(413, "upload_too_large", "图片大小超过限制") from exc

    asset = UploadedAsset(
        user_id=current_user.id,
        storage_name=storage_name,
        original_name=original_name,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


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
