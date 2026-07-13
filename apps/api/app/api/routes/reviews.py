from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.core.errors import APIError
from app.models.question import Question
from app.models.review import ReviewRecord, UserSettings
from app.schemas.review import (
    ReviewRecordRead,
    ReviewRecordPage,
    ReviewSettingsRead,
    ReviewSettingsUpdate,
    ReviewSubmit,
    TodayReviewResponse,
)
from app.services.review import get_today_review


router = APIRouter(prefix="/reviews", tags=["reviews"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/today", response_model=TodayReviewResponse)
async def today_review(
    current_user: CurrentUser, session: Session
) -> TodayReviewResponse:
    return await get_today_review(session, current_user.id)


@router.patch("/settings", response_model=ReviewSettingsRead)
async def update_review_settings(
    payload: ReviewSettingsUpdate, current_user: CurrentUser, session: Session
) -> ReviewSettingsRead:
    settings = await session.scalar(
        select(UserSettings).where(UserSettings.user_id == current_user.id)
    )
    if settings is None:
        settings = UserSettings(
            user_id=current_user.id, daily_review_limit=payload.daily_review_limit
        )
        session.add(settings)
    else:
        settings.daily_review_limit = payload.daily_review_limit
    await session.commit()
    return ReviewSettingsRead(daily_review_limit=settings.daily_review_limit)


@router.get(
    "/questions/{question_id}",
    response_model=ReviewRecordPage,
)
async def question_review_history(
    question_id: str,
    current_user: CurrentUser,
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReviewRecordPage:
    question = await session.scalar(
        select(Question).where(
            Question.id == question_id, Question.user_id == current_user.id
        )
    )
    if question is None:
        raise APIError(404, "not_found", "错题不存在")

    filters = [
        ReviewRecord.question_id == question.id,
        ReviewRecord.user_id == current_user.id,
    ]
    total = await session.scalar(
        select(func.count()).select_from(ReviewRecord).where(*filters)
    )
    records = await session.scalars(
        select(ReviewRecord)
        .where(*filters)
        .order_by(ReviewRecord.reviewed_at.desc(), ReviewRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ReviewRecordPage(
        items=list(records),
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post(
    "/{question_id}",
    response_model=ReviewRecordRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_review(
    question_id: str,
    payload: ReviewSubmit,
    current_user: CurrentUser,
    session: Session,
) -> ReviewRecord:
    question = await session.scalar(
        select(Question).where(
            Question.id == question_id, Question.user_id == current_user.id
        )
    )
    if question is None:
        raise APIError(404, "not_found", "错题不存在")
    record = ReviewRecord(
        question_id=question.id,
        user_id=current_user.id,
        result_status=payload.result_status.value,
        review_note=payload.review_note,
    )
    question.mastery_status = payload.result_status.value
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record
