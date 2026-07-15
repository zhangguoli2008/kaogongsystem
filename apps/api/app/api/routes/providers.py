from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OCRServiceDep
from app.core.database import get_session
from app.core.errors import APIError, request_id_for
from app.models.upload import UploadedAsset
from app.schemas.ocr import OcrResult
from app.schemas.upload import OcrRequest

router = APIRouter(tags=["ocr"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/ocr", response_model=OcrResult)
async def ocr_upload(
    payload: OcrRequest,
    current_user: CurrentUser,
    session: Session,
    request: Request,
    ocr_service: OCRServiceDep,
) -> OcrResult:
    asset = await session.scalar(
        select(UploadedAsset).where(
            UploadedAsset.id == payload.upload_id,
            UploadedAsset.user_id == current_user.id,
        )
    )
    if asset is None:
        raise APIError(404, "OCR_SOURCE_NOT_FOUND", "未找到上传文件")

    # The optional client key is accepted for retry-compatible clients, but the
    # service deliberately derives its authoritative key from user/file/page/
    # provider/parameter-version data.
    return await ocr_service.recognize(
        session,
        user_id=current_user.id,
        asset=asset,
        pdf_page_number=payload.pdf_page_number,
        local_request_id=request_id_for(request),
    )
