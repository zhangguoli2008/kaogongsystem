"""Provider-neutral OCR response schemas exposed by the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OcrModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OcrPoint(OcrModel):
    x: int
    y: int


class OcrPolygon(OcrModel):
    left_top: OcrPoint | None = None
    right_top: OcrPoint | None = None
    right_bottom: OcrPoint | None = None
    left_bottom: OcrPoint | None = None


class OcrTextElement(OcrModel):
    index: int | None = None
    text: str | None = None
    coord: OcrPolygon | None = None


class OcrOption(OcrModel):
    label: str
    text: str
    raw_text: str
    coord: OcrPolygon | None = None
    asset_id: str | None = None
    image_url: str | None = None


class OcrMedia(OcrModel):
    index: int | None = None
    text: str | None = None
    coord: OcrPolygon | None = None
    asset_id: str | None = None
    image_url: str | None = None


class OcrSource(OcrModel):
    file_id: str
    image_url: str
    original_width: int | None = None
    original_height: int | None = None
    processed_width: int | None = None
    processed_height: int | None = None
    angle: float | None = None


OcrQuestionType = Literal[
    "multiple_choice_unknown",
    "fill_blank",
    "problem_solving",
    "arithmetic",
    "unknown",
]


class OcrQuestion(OcrModel):
    temporary_id: str
    index: int | None = None
    source_info_index: int = Field(ge=0)
    question_number: str | None = None
    question_type: OcrQuestionType
    question_text: str
    full_text: str
    question_elements: list[OcrTextElement] = Field(default_factory=list)
    options: list[OcrOption] = Field(default_factory=list)
    figures: list[OcrMedia] = Field(default_factory=list)
    tables: list[OcrMedia] = Field(default_factory=list)
    recognized_answer: str | None = None
    recognized_parse: str | None = None
    coord: list[OcrPolygon] = Field(default_factory=list)
    raw_group_type: str | None = None
    warnings: list[str] = Field(default_factory=list)
    crop_asset_id: str | None = None
    crop_image_url: str | None = None


class OcrResult(OcrModel):
    provider: str
    api_name: Literal["QuestionSplitOCR"]
    request_id: str
    page_number: int = Field(ge=1)
    question_count: int = Field(ge=0)
    source: OcrSource
    warnings: list[str] = Field(default_factory=list)
    questions: list[OcrQuestion] = Field(default_factory=list)
    is_demo: bool = False
