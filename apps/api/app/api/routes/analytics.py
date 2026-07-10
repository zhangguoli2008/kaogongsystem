from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.schemas.analytics import AnalyticsSummary
from app.services.analytics import get_analytics_summary


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
