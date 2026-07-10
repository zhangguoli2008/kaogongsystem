from __future__ import annotations

from app.schemas.question import QuestionRead
from app.schemas.review import TodayReviewResponse

from pydantic import BaseModel, Field


class CountByLabel(BaseModel):
    label: str
    count: int = Field(ge=0)


class TrendPoint(BaseModel):
    date: str
    count: int = Field(ge=0)


class AnalyticsSummary(BaseModel):
    total_questions: int = Field(ge=0)
    module_distribution: list[CountByLabel]
    knowledge_point_ranking: list[CountByLabel]
    error_reason_distribution: list[CountByLabel]
    mastery_distribution: list[CountByLabel]
    trend_7d: list[TrendPoint]
    trend_30d: list[TrendPoint]
    ai_summary: str
    is_demo: bool


class DashboardResponse(BaseModel):
    today_review: TodayReviewResponse
    current_question: QuestionRead | None
    recent_questions: list[QuestionRead]
    weak_modules: list[CountByLabel]
    trend_7d: list[TrendPoint]
    ai_advice: str
    provider_mode: str
