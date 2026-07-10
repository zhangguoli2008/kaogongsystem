from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.question import Question
from app.schemas.analytics import AnalyticsSummary, CountByLabel, TrendPoint
from app.schemas.question import MasteryStatus
from app.services.review import _knowledge_point_rows, utc_now


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_date_bucket(session: AsyncSession):
    """Return the database date expression for the same UTC day as filters."""

    if session.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone("UTC", Question.created_at)).label("date")
    return func.date(Question.created_at).label("date")


async def _count_distribution(
    session: AsyncSession,
    user_id: str,
    column,
    *,
    unfinished_only: bool = False,
) -> list[CountByLabel]:
    count = func.count().label("count")
    filters = [Question.user_id == user_id, column.is_not(None)]
    if unfinished_only:
        filters.append(Question.mastery_status != MasteryStatus.MASTERED.value)
    rows = await session.execute(
        select(column.label("label"), count)
        .where(*filters)
        .group_by(column)
        .order_by(count.desc(), column.asc())
    )
    return [CountByLabel(label=str(row.label), count=int(row.count)) for row in rows]


async def knowledge_point_ranking(
    session: AsyncSession, user_id: str
) -> list[CountByLabel]:
    points = _knowledge_point_rows(session)
    count = func.count().label("count")
    rows = await session.execute(
        select(points.c.value.label("label"), count)
        .select_from(Question)
        .join(points, true())
        .where(Question.user_id == user_id)
        .group_by(points.c.value)
        .order_by(count.desc(), points.c.value.asc())
    )
    return [CountByLabel(label=str(row.label), count=int(row.count)) for row in rows]


async def trend_for_days(
    session: AsyncSession,
    user_id: str,
    days: int,
    now: datetime | None = None,
) -> list[TrendPoint]:
    current = _as_utc(now or utc_now())
    start_date = current.date() - timedelta(days=days - 1)
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
    date_column = _utc_date_bucket(session)
    count = func.count().label("count")
    rows = await session.execute(
        select(date_column, count)
        .where(
            Question.user_id == user_id,
            Question.created_at >= start,
            Question.created_at < end,
        )
        .group_by(date_column)
    )
    counts = {str(row.date): int(row.count) for row in rows}
    return [
        TrendPoint(
            date=(start_date + timedelta(days=index)).isoformat(),
            count=counts.get((start_date + timedelta(days=index)).isoformat(), 0),
        )
        for index in range(days)
    ]


def build_ai_summary(
    module_distribution: list[CountByLabel],
    knowledge_points: list[CountByLabel],
    is_demo: bool,
) -> str:
    if not module_distribution:
        return "先录入错题，系统会根据你的数据生成学习建议。"
    module = module_distribution[0].label
    knowledge_point = knowledge_points[0].label if knowledge_points else "核心知识点"
    if is_demo:
        return (
            f"演示建议：优先复习{module}中的{knowledge_point}，"
            "再用一组同类题检验掌握情况。"
        )
    return "统计已汇总。点击刷新 AI 建议后才会请求真实 Provider。"


async def get_analytics_summary(
    session: AsyncSession,
    user_id: str,
    settings: Settings,
    now: datetime | None = None,
) -> AnalyticsSummary:
    total = await session.scalar(
        select(func.count()).select_from(Question).where(Question.user_id == user_id)
    )
    module_distribution = await _count_distribution(session, user_id, Question.module)
    points = await knowledge_point_ranking(session, user_id)
    error_reasons = await _count_distribution(session, user_id, Question.error_reason)
    mastery = await _count_distribution(session, user_id, Question.mastery_status)
    is_demo = settings.effective_provider_mode == "demo"
    return AnalyticsSummary(
        total_questions=total or 0,
        module_distribution=module_distribution,
        knowledge_point_ranking=points,
        error_reason_distribution=error_reasons,
        mastery_distribution=mastery,
        trend_7d=await trend_for_days(session, user_id, 7, now),
        trend_30d=await trend_for_days(session, user_id, 30, now),
        ai_summary=build_ai_summary(module_distribution, points, is_demo),
        is_demo=is_demo,
    )


async def get_weak_modules(
    session: AsyncSession, user_id: str, limit: int = 3
) -> list[CountByLabel]:
    return (await _count_distribution(
        session, user_id, Question.module, unfinished_only=True
    ))[:limit]
