from __future__ import annotations

from app.schemas.question import QuestionRead
from app.schemas.review import TodayReviewResponse

from pydantic import BaseModel, ConfigDict, Field


class CountByLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    count: int = Field(ge=0)


class TrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class AnalyticsAdviceInput(BaseModel):
    """Server-owned analytics supplied to an advice provider."""

    model_config = ConfigDict(extra="forbid")

    total_questions: int = Field(ge=0)
    module_distribution: list[CountByLabel]
    knowledge_point_ranking: list[CountByLabel]
    error_reason_distribution: list[CountByLabel]
    mastery_distribution: list[CountByLabel]
    trend_7d: list[TrendPoint]
    trend_30d: list[TrendPoint]


class AnalyticsAdviceProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advice: str = Field(min_length=1, max_length=4000)


class AnalyticsAdviceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advice: str = Field(min_length=1, max_length=4000)
    provider_name: str
    model_name: str | None
    is_demo: bool
