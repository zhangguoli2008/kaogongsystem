from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.core.errors import APIError, request_id_for
from app.schemas.analytics import (
    AnalyticsAdviceInput,
    AnalyticsAdviceResult,
    AnalyticsSummary,
)
from app.services.analytics import get_analytics_summary
from app.services.providers.factory import get_provider


router = APIRouter(prefix="/analytics", tags=["analytics"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(
    current_user: CurrentUser, session: Session, request: Request
) -> AnalyticsSummary:
    # This read-only endpoint deliberately never invokes a live Provider.
    return await get_analytics_summary(
        session, current_user.id, request.app.state.settings
    )


@router.post("/advice", response_model=AnalyticsAdviceResult)
async def analytics_advice(
    current_user: CurrentUser, session: Session, request: Request
) -> AnalyticsAdviceResult:
    if not request.app.state.provider_rate_limiter.allow(current_user.id):
        raise APIError(
            429,
            "provider_rate_limited",
            "AI 建议请求过于频繁，请稍后再试",
        )
    summary = await get_analytics_summary(
        session, current_user.id, request.app.state.settings
    )
    payload = AnalyticsAdviceInput(
        total_questions=summary.total_questions,
        module_distribution=summary.module_distribution,
        knowledge_point_ranking=summary.knowledge_point_ranking,
        error_reason_distribution=summary.error_reason_distribution,
        mastery_distribution=summary.mastery_distribution,
        trend_7d=summary.trend_7d,
        trend_30d=summary.trend_30d,
    )
    provider = get_provider(request.app.state.settings)
    result = await provider.advise(payload, request_id=request_id_for(request))
    try:
        return AnalyticsAdviceResult.model_validate(result)
    except (ValidationError, TypeError, ValueError) as exc:
        raise APIError(
            502,
            "provider_invalid_response",
            "AI 建议服务返回内容无效",
        ) from exc
