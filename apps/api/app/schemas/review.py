from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Pagination
from app.schemas.question import MasteryStatus, QuestionRead


class ReviewSubmit(BaseModel):
    result_status: MasteryStatus
    review_note: str | None = Field(default=None, max_length=20000)


class ReviewRecordRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    question_id: str
    user_id: str
    result_status: MasteryStatus
    review_note: str | None
    reviewed_at: datetime


class ReviewRecordPage(Pagination):
    items: list[ReviewRecordRead]


class ReviewSettingsUpdate(BaseModel):
    daily_review_limit: Literal[10, 20, 30, 50]


class ReviewSettingsRead(BaseModel):
    daily_review_limit: Literal[10, 20, 30, 50]


class TodayReviewResponse(BaseModel):
    daily_review_limit: Literal[10, 20, 30, 50]
    pending: list[QuestionRead]
    completed: list[ReviewRecordRead]
    completed_count: int = Field(ge=0)
    total: int = Field(ge=0)
