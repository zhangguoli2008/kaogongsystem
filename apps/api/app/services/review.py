from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import cast

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import TableValuedAlias

from app.models.question import Question
from app.models.review import ReviewRecord, UserSettings
from app.schemas.question import MasteryStatus, QuestionRead
from app.schemas.review import (
    DailyReviewLimit,
    ReviewRecordRead,
    TodayReviewResponse,
)


ALLOWED_DAILY_REVIEW_LIMITS = frozenset({10, 20, 30, 50})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    current = _as_utc(now)
    start = datetime.combine(current.date(), time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _knowledge_point_rows(session: AsyncSession) -> TableValuedAlias:
    if session.get_bind().dialect.name == "postgresql":
        return func.json_array_elements_text(Question.knowledge_points).table_valued(
            "value"
        )
    return func.json_each(Question.knowledge_points).table_valued("value")


async def get_weak_knowledge_points(
    session: AsyncSession, user_id: str, limit: int = 3
) -> set[str]:
    """Return the user's most frequent unfinished knowledge points.

    All candidates are wrong questions already; limiting this aggregation to
    unfinished statuses makes the bonus reflect the currently weak areas.
    """

    points = _knowledge_point_rows(session)
    count = func.count().label("count")
    rows = await session.execute(
        select(points.c.value)
        .select_from(Question)
        .join(points, true())
        .where(
            Question.user_id == user_id,
            Question.mastery_status.in_(
                [MasteryStatus.UNMASTERED.value, MasteryStatus.REVIEWING.value]
            ),
        )
        .group_by(points.c.value)
        .order_by(count.desc(), points.c.value.asc())
        .limit(limit)
    )
    return {str(value) for value in rows.scalars()}


def score_review_candidate(
    question: Question, weak_points: set[str], now: datetime
) -> int:
    """Score one review candidate using the approved additive policy."""

    score = 0
    if question.mastery_status == MasteryStatus.UNMASTERED.value:
        score += 100
    elif question.mastery_status == MasteryStatus.REVIEWING.value:
        score += 60
    if _as_utc(question.created_at) >= _as_utc(now) - timedelta(days=7):
        score += 30
    if weak_points.intersection(question.knowledge_points):
        score += 20
    return score


async def get_daily_review_limit(
    session: AsyncSession, user_id: str
) -> DailyReviewLimit:
    limit = await session.scalar(
        select(UserSettings.daily_review_limit).where(UserSettings.user_id == user_id)
    )
    if limit is None:
        # Registration creates settings atomically. Keeping this fallback makes
        # a partially imported legacy account retain the documented default.
        return 20
    if limit not in ALLOWED_DAILY_REVIEW_LIMITS:
        raise ValueError("daily_review_limit must be one of 10, 20, 30, 50")
    return cast(DailyReviewLimit, limit)


async def get_today_review(
    session: AsyncSession, user_id: str, now: datetime | None = None
) -> TodayReviewResponse:
    current = _as_utc(now or utc_now())
    day_start, next_day_start = _day_bounds(current)
    daily_limit = await get_daily_review_limit(session, user_id)
    completed = list(
        await session.scalars(
            select(ReviewRecord)
            .where(
                ReviewRecord.user_id == user_id,
                ReviewRecord.reviewed_at >= day_start,
                ReviewRecord.reviewed_at < next_day_start,
            )
            .order_by(ReviewRecord.reviewed_at.desc(), ReviewRecord.id.desc())
        )
    )
    completed_question_ids = {record.question_id for record in completed}
    weak_points = await get_weak_knowledge_points(session, user_id)
    candidates = list(
        await session.scalars(
            select(Question).where(
                Question.user_id == user_id,
                (
                    Question.mastery_status.in_(
                        [
                            MasteryStatus.UNMASTERED.value,
                            MasteryStatus.REVIEWING.value,
                        ]
                    )
                    | (Question.created_at >= current - timedelta(days=7))
                ),
            )
        )
    )
    pending = [
        question for question in candidates if question.id not in completed_question_ids
    ]
    pending.sort(
        key=lambda question: (
            score_review_candidate(question, weak_points, current),
            _as_utc(question.created_at).timestamp(),
            question.id,
        ),
        reverse=True,
    )
    # Today's completed questions consume the same daily quota.  Without this
    # remaining-capacity cap, a completed item would be replaced by another
    # pending item and users could receive more than their configured count.
    remaining_capacity = max(0, daily_limit - len(completed_question_ids))
    pending = pending[:remaining_capacity]
    return TodayReviewResponse(
        daily_review_limit=daily_limit,
        pending=[QuestionRead.model_validate(question) for question in pending],
        completed=[ReviewRecordRead.model_validate(record) for record in completed],
        completed_count=len(completed_question_ids),
        total=len(pending) + len(completed_question_ids),
    )
