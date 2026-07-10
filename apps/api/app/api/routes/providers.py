from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.core.errors import APIError, request_id_for
from app.models.upload import UploadedAsset
from app.schemas.upload import OcrRequest, OcrResult
from app.services.providers.factory import get_provider
from app.services.storage import image_path

router = APIRouter(tags=["providers"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/ocr", response_model=OcrResult)
async def ocr_upload(
    payload: OcrRequest,
    current_user: CurrentUser,
    session: Session,
    request: Request,
) -> OcrResult:
    asset = await session.scalar(
        select(UploadedAsset).where(
            UploadedAsset.id == payload.upload_id,
            UploadedAsset.user_id == current_user.id,
        )
    )
    if asset is None:
        raise APIError(404, "not_found", "上传文件不存在")
    if not request.app.state.provider_rate_limiter.allow(current_user.id):
        raise APIError(429, "provider_rate_limited", "OCR 请求过于频繁，请稍后再试")
    try:
        path = image_path(request.app.state.settings.upload_dir, asset.storage_name)
        image_bytes = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise APIError(404, "not_found", "上传文件不存在") from exc
    provider = get_provider(request.app.state.settings)
    return await provider.ocr(
        image_bytes, asset.mime_type, request_id=request_id_for(request)
    )
