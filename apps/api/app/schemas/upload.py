from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.question import QuestionOption


class UploadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_name: str
    storage_name: str
    mime_type: str
    size_bytes: int
    created_at: datetime


class OcrRequest(BaseModel):
    upload_id: str = Field(min_length=1, max_length=36)


class OcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stem: str = Field(min_length=1)
    options: list[QuestionOption] = Field(min_length=1)
    user_answer: str = ""
    correct_answer: str = Field(min_length=1)
    original_explanation: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    is_demo: bool
