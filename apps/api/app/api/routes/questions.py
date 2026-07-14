from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.core.errors import APIError, request_id_for
from app.models.analysis import Analysis
from app.models.question import Question
from app.models.upload import UploadedAsset
from app.schemas.analysis import AnalysisImage, AnalysisInput, AnalysisResult
from app.schemas.common import BulkIds
from app.schemas.question import (
    AnalysisStatus,
    BulkStatusRequest,
    ErrorReason,
    ExamModule,
    MasteryStatus,
    QuestionCreate,
    AnalysisRead,
    QuestionOcrAsset,
    QuestionOcrMetadata,
    QuestionPage,
    QuestionRead,
    QuestionUpdate,
)
from app.services.providers.factory import get_provider
from app.services.storage import (
    InvalidImage,
    UnsupportedImageType,
    image_path,
    inspect_image,
)

router = APIRouter(prefix="/questions", tags=["questions"])
Session = Annotated[AsyncSession, Depends(get_session)]
SUPPORTED_ANALYSIS_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/bmp"}
SUPPORTED_OCR_SOURCE_MIME_TYPES = {
    *SUPPORTED_ANALYSIS_IMAGE_MIME_TYPES,
    "application/pdf",
}
MAX_ANALYSIS_IMAGES = 8
MAX_ANALYSIS_IMAGE_TOTAL_BYTES = 20 * 1024 * 1024


def _not_found() -> APIError:
    return APIError(404, "not_found", "错题不存在")


async def _get_owned_question(
    question_id: str, user_id: str, session: AsyncSession
) -> Question:
    question = await session.scalar(
        select(Question).where(Question.id == question_id, Question.user_id == user_id)
    )
    if question is None:
        raise _not_found()
    return question


def _invalid_ocr_asset_reference() -> APIError:
    return APIError(422, "invalid_ocr_asset_reference", "OCR 图片资源引用无效")


def _ocr_asset_references(
    metadata: QuestionOcrMetadata,
) -> list[tuple[QuestionOcrAsset, bool]]:
    references: list[tuple[QuestionOcrAsset, bool]] = [(metadata.source, False)]
    if metadata.crop is not None:
        references.append((metadata.crop, True))
    for item in (*metadata.figures, *metadata.tables, *metadata.options):
        if item.asset is not None:
            references.append((item.asset, True))
    return references


def _analysis_asset_references(
    metadata: QuestionOcrMetadata,
) -> list[QuestionOcrAsset]:
    references: list[QuestionOcrAsset] = []
    if metadata.crop is not None:
        references.append(metadata.crop)
    for item in (*metadata.figures, *metadata.tables, *metadata.options):
        if item.asset is not None:
            references.append(item.asset)
    references.append(metadata.source)
    return references


def _verified_provider_image(
    content: bytes,
    *,
    expected_mime_type: str,
) -> tuple[str, bytes]:
    detected_mime_type, _ = inspect_image(content)
    if detected_mime_type != expected_mime_type:
        raise InvalidImage
    if detected_mime_type != "image/bmp":
        return detected_mime_type, content

    with Image.open(BytesIO(content)) as image:
        image.load()
        with image.convert("RGB") as converted_image, BytesIO() as output:
            converted_image.save(output, format="PNG")
            converted = output.getvalue()
    converted_mime_type, _ = inspect_image(converted)
    if converted_mime_type != "image/png":
        raise InvalidImage
    return converted_mime_type, converted


async def _validate_ocr_metadata_assets(
    metadata: QuestionOcrMetadata,
    *,
    user_id: str,
    session: AsyncSession,
    upload_dir: Path,
) -> tuple[QuestionOcrMetadata, dict[str, UploadedAsset]]:
    normalized = metadata.model_copy(deep=True)
    references = _ocr_asset_references(normalized)
    asset_ids = {str(reference.asset_id) for reference, _ in references}

    for reference, _ in references:
        expected_url = f"/uploads/{reference.asset_id}"
        if reference.image_url not in {None, expected_url}:
            raise _invalid_ocr_asset_reference()

    assets = list(
        await session.scalars(
            select(UploadedAsset).where(
                UploadedAsset.user_id == user_id,
                UploadedAsset.id.in_(asset_ids),
            )
        )
    )
    assets_by_id = {asset.id: asset for asset in assets}
    if set(assets_by_id) != asset_ids:
        raise _invalid_ocr_asset_reference()

    for reference, image_required in references:
        asset = assets_by_id[str(reference.asset_id)]
        allowed_mime_types = (
            SUPPORTED_ANALYSIS_IMAGE_MIME_TYPES
            if image_required
            else SUPPORTED_OCR_SOURCE_MIME_TYPES
        )
        if asset.mime_type not in allowed_mime_types:
            raise _invalid_ocr_asset_reference()
        try:
            path = image_path(upload_dir, asset.storage_name)
        except ValueError as exc:
            raise _invalid_ocr_asset_reference() from exc
        if not path.is_file():
            raise _invalid_ocr_asset_reference()
        reference.image_url = f"/uploads/{reference.asset_id}"

    return normalized, assets_by_id


async def _prepare_ocr_metadata(
    metadata: QuestionOcrMetadata,
    *,
    user_id: str,
    session: AsyncSession,
    upload_dir: Path,
) -> dict[str, object]:
    normalized, _ = await _validate_ocr_metadata_assets(
        metadata,
        user_id=user_id,
        session=session,
        upload_dir=upload_dir,
    )
    return normalized.model_dump(mode="json")


async def _load_analysis_images(
    raw_metadata: dict[str, object] | None,
    *,
    user_id: str,
    session: AsyncSession,
    upload_dir: Path,
) -> list[AnalysisImage]:
    if raw_metadata is None:
        return []
    try:
        metadata = QuestionOcrMetadata.model_validate(raw_metadata)
    except ValidationError as exc:
        raise _invalid_ocr_asset_reference() from exc
    normalized, assets_by_id = await _validate_ocr_metadata_assets(
        metadata,
        user_id=user_id,
        session=session,
        upload_dir=upload_dir,
    )

    images: list[AnalysisImage] = []
    seen_asset_ids: set[str] = set()
    total_bytes = 0
    for reference in _analysis_asset_references(normalized):
        asset_id = str(reference.asset_id)
        if asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        asset = assets_by_id[asset_id]
        if asset.mime_type not in SUPPORTED_ANALYSIS_IMAGE_MIME_TYPES:
            continue
        if len(images) >= MAX_ANALYSIS_IMAGES:
            break
        path = image_path(upload_dir, asset.storage_name)
        try:
            actual_size = path.stat().st_size
            if actual_size <= 0:
                raise _invalid_ocr_asset_reference()
            if actual_size > MAX_ANALYSIS_IMAGE_TOTAL_BYTES:
                continue
            content = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise _invalid_ocr_asset_reference() from exc
        if len(content) != actual_size:
            raise _invalid_ocr_asset_reference()
        try:
            provider_mime_type, provider_content = await asyncio.to_thread(
                _verified_provider_image,
                content,
                expected_mime_type=asset.mime_type,
            )
        except (InvalidImage, UnsupportedImageType, OSError, ValueError) as exc:
            raise _invalid_ocr_asset_reference() from exc
        if total_bytes + len(provider_content) > MAX_ANALYSIS_IMAGE_TOTAL_BYTES:
            continue
        images.append(
            AnalysisImage(mime_type=provider_mime_type, content=provider_content)
        )
        total_bytes += len(provider_content)
    return images


def _knowledge_point_filter(knowledge_point: str, session: AsyncSession):
    """Return an EXISTS predicate that works with SQLite and PostgreSQL JSON arrays."""
    if session.get_bind().dialect.name == "postgresql":
        points = func.json_array_elements_text(
            Question.knowledge_points
        ).table_valued("value")
    else:
        points = func.json_each(Question.knowledge_points).table_valued("value")
    return (
        select(1)
        .select_from(points)
        .where(points.c.value == knowledge_point)
        .correlate(Question)
        .exists()
    )


@router.post("", response_model=QuestionRead, status_code=status.HTTP_201_CREATED)
async def create_question(
    payload: QuestionCreate,
    current_user: CurrentUser,
    session: Session,
    request: Request,
) -> Question:
    values = payload.model_dump(mode="json")
    if payload.ocr_metadata is not None:
        values["ocr_metadata"] = await _prepare_ocr_metadata(
            payload.ocr_metadata,
            user_id=current_user.id,
            session=session,
            upload_dir=request.app.state.settings.upload_dir,
        )
    values["user_id"] = current_user.id
    question = Question(**values)
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return question


@router.get("", response_model=QuestionPage)
async def list_questions(
    current_user: CurrentUser,
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    module: ExamModule | None = None,
    knowledge_point: str | None = Query(default=None, min_length=1),
    error_reason: ErrorReason | None = None,
    mastery_status: MasteryStatus | None = None,
    analysis_status: AnalysisStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> QuestionPage:
    filters = [Question.user_id == current_user.id]
    if module is not None:
        filters.append(Question.module == module.value)
    if knowledge_point is not None:
        filters.append(_knowledge_point_filter(knowledge_point, session))
    if error_reason is not None:
        filters.append(Question.error_reason == error_reason.value)
    if mastery_status is not None:
        filters.append(Question.mastery_status == mastery_status.value)
    if analysis_status is not None:
        filters.append(Question.analysis_status == analysis_status.value)
    if created_from is not None:
        filters.append(Question.created_at >= created_from)
    if created_to is not None:
        filters.append(Question.created_at <= created_to)

    count = await session.scalar(
        select(func.count()).select_from(Question).where(*filters)
    )
    result = await session.scalars(
        select(Question)
        .where(*filters)
        .order_by(Question.created_at.desc(), Question.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return QuestionPage(
        items=list(result), page=page, page_size=page_size, total=count or 0
    )


@router.post("/bulk-status")
async def bulk_update_status(
    payload: BulkStatusRequest, current_user: CurrentUser, session: Session
) -> dict[str, int | list[str]]:
    questions = list(
        await session.scalars(
            select(Question).where(
                Question.user_id == current_user.id, Question.id.in_(payload.ids)
            )
        )
    )
    found_ids = {question.id for question in questions}
    not_found = [
        question_id for question_id in payload.ids if question_id not in found_ids
    ]
    for question in questions:
        question.mastery_status = payload.mastery_status.value
    await session.commit()
    return {"updated": len(questions), "not_found": not_found}


@router.post("/bulk-delete")
async def bulk_delete(
    payload: BulkIds, current_user: CurrentUser, session: Session
) -> dict[str, int | list[str]]:
    questions = list(
        await session.scalars(
            select(Question).where(
                Question.user_id == current_user.id, Question.id.in_(payload.ids)
            )
        )
    )
    found_ids = {question.id for question in questions}
    not_found = [
        question_id for question_id in payload.ids if question_id not in found_ids
    ]
    for question in questions:
        await session.delete(question)
    await session.commit()
    return {"deleted": len(questions), "not_found": not_found}


@router.get("/{question_id}", response_model=QuestionRead)
async def read_question(
    question_id: str, current_user: CurrentUser, session: Session
) -> Question:
    return await _get_owned_question(question_id, current_user.id, session)


@router.patch("/{question_id}", response_model=QuestionRead)
async def update_question(
    question_id: str,
    payload: QuestionUpdate,
    current_user: CurrentUser,
    session: Session,
    request: Request,
) -> Question:
    question = await _get_owned_question(question_id, current_user.id, session)
    values = payload.model_dump(exclude_unset=True, mode="json")
    if "ocr_metadata" in payload.model_fields_set and payload.ocr_metadata is not None:
        values["ocr_metadata"] = await _prepare_ocr_metadata(
            payload.ocr_metadata,
            user_id=current_user.id,
            session=session,
            upload_dir=request.app.state.settings.upload_dir,
        )
    for key, value in values.items():
        setattr(question, key, value)
    await session.commit()
    await session.refresh(question)
    return question


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: str, current_user: CurrentUser, session: Session
) -> Response:
    question = await _get_owned_question(question_id, current_user.id, session)
    await session.delete(question)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_ANALYSIS_ERROR_MESSAGES = {
    "provider_timeout": "AI 分析服务响应超时",
    "provider_connection_error": "AI 分析服务连接失败",
    "provider_rate_limited": "AI 分析服务请求过于频繁",
    "provider_invalid_response": "AI 分析服务返回内容无效",
    "provider_api_error": "AI 分析服务暂时不可用",
}


def _safe_analysis_provider_error(exc: APIError) -> APIError:
    message = _ANALYSIS_ERROR_MESSAGES.get(exc.code)
    if message is None:
        return APIError(
            502, "provider_api_error", _ANALYSIS_ERROR_MESSAGES["provider_api_error"]
        )
    return APIError(exc.status_code, exc.code, message)


async def _persist_analysis_failure(
    *, session: AsyncSession, question_id: str, user_id: str, code: str
) -> None:
    """Discard partial analysis work, then persist only the public failure state."""

    await session.rollback()
    await session.execute(
        update(Question)
        .where(Question.id == question_id, Question.user_id == user_id)
        .values(
            analysis_status=AnalysisStatus.FAILED.value,
            analysis_error_code=code,
        )
    )
    await session.commit()


@router.post("/{question_id}/analyze", response_model=AnalysisRead)
async def analyze_question(
    question_id: str,
    current_user: CurrentUser,
    session: Session,
    request: Request,
) -> Analysis:
    question = await _get_owned_question(question_id, current_user.id, session)
    if not request.app.state.provider_rate_limiter.allow(current_user.id):
        raise APIError(429, "provider_rate_limited", "AI 分析请求过于频繁，请稍后再试")

    images = await _load_analysis_images(
        question.ocr_metadata,
        user_id=current_user.id,
        session=session,
        upload_dir=request.app.state.settings.upload_dir,
    )

    question.analysis_status = AnalysisStatus.ANALYZING.value
    question.analysis_error_code = None
    await session.commit()

    try:
        payload = AnalysisInput(
            stem=question.stem,
            options=question.options,
            user_answer=question.user_answer,
            correct_answer=question.correct_answer,
            original_explanation=question.original_explanation or "",
            ocr_raw_text=question.ocr_raw_text or "",
            module=ExamModule(question.module),
        )
        provider = get_provider(request.app.state.settings)
        if images:
            provider_result = await provider.analyze(
                payload,
                request_id=request_id_for(request),
                images=images,
            )
        else:
            provider_result = await provider.analyze(
                payload, request_id=request_id_for(request)
            )
        if not isinstance(provider_result, AnalysisResult):
            raise APIError(
                502,
                "provider_invalid_response",
                _ANALYSIS_ERROR_MESSAGES["provider_invalid_response"],
            )
        try:
            result = AnalysisResult.model_validate(
                provider_result.model_dump(mode="json", warnings="error")
            )
        except (TypeError, ValueError) as exc:
            raise APIError(
                502, "provider_invalid_response", _ANALYSIS_ERROR_MESSAGES["provider_invalid_response"]
            ) from exc

        analysis = Analysis(
            question_id=question.id,
            user_id=current_user.id,
            **result.model_dump(mode="json"),
        )
        session.add(analysis)
        await session.flush()
        await session.refresh(analysis)
        question.current_analysis_id = analysis.id
        question.knowledge_points = result.knowledge_points
        question.error_reason = result.suggested_error_reason.value
        question.analysis_status = AnalysisStatus.COMPLETED.value
        question.analysis_error_code = None
        await session.commit()
        return analysis
    except APIError as exc:
        public_error = _safe_analysis_provider_error(exc)
        await _persist_analysis_failure(
            session=session,
            question_id=question.id,
            user_id=current_user.id,
            code=public_error.code,
        )
        raise public_error from exc
    except Exception as exc:
        code = "provider_api_error"
        await _persist_analysis_failure(
            session=session,
            question_id=question.id,
            user_id=current_user.id,
            code=code,
        )
        raise APIError(
            502, code, _ANALYSIS_ERROR_MESSAGES[code]
        ) from exc
