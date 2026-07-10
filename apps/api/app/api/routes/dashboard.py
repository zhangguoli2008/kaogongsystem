from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.models.question import Question
from app.schemas.analytics import DashboardResponse
from app.services.analytics import get_analytics_summary, get_weak_modules
from app.services.review import get_today_review


router = APIRouter(tags=["dashboard"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    current_user: CurrentUser, session: Session, request: Request
) -> DashboardResponse:
    today = await get_today_review(session, current_user.id)
    summary = await get_analytics_summary(
        session, current_user.id, request.app.state.settings
    )
    recent_questions = list(
        await session.scalars(
            select(Question)
            .where(Question.user_id == current_user.id)
            .order_by(Question.created_at.desc(), Question.id.desc())
            .limit(5)
        )
    )
    return DashboardResponse(
        today_review=today,
        current_question=today.pending[0] if today.pending else None,
        recent_questions=recent_questions,
        weak_modules=await get_weak_modules(session, current_user.id),
        trend_7d=summary.trend_7d,
        ai_advice=summary.ai_summary,
        provider_mode=request.app.state.settings.effective_provider_mode,
    )
