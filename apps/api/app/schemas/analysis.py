from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.question import ErrorReason, ExamModule, QuestionOption


class AnalysisInput(BaseModel):
    """Question fields supplied to an AI analysis provider."""

    model_config = ConfigDict(extra="forbid")

    stem: str
    options: list[QuestionOption]
    user_answer: str
    correct_answer: str
    original_explanation: str = ""
    ocr_raw_text: str = ""
    module: ExamModule


class AnalysisResult(BaseModel):
    """Validated result persisted for one manual analysis attempt."""

    model_config = ConfigDict(extra="forbid")

    cause_analysis: str
    knowledge_points: list[str]
    correct_approach: str
    study_advice: str
    suggested_error_reason: ErrorReason
    raw_response: dict[str, object]
    provider_name: str
    model_name: str | None
    is_demo: bool


class AnalysisProviderResponse(BaseModel):
    """Strict response shape requested from the Responses API."""

    model_config = ConfigDict(extra="forbid")

    cause_analysis: str
    knowledge_points: list[str]
    correct_approach: str
    study_advice: str
    suggested_error_reason: ErrorReason
