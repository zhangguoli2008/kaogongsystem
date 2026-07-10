from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import Pagination


class ExamType(str, Enum):
    NATIONAL = "国考"
    PROVINCIAL = "省考"
    INSTITUTION = "事业编"
    OTHER = "其他"


class ExamModule(str, Enum):
    VERBAL = "言语理解"
    QUANT = "数量关系"
    REASONING = "判断推理"
    DATA = "资料分析"
    KNOWLEDGE = "常识判断"


class ErrorReason(str, Enum):
    CARELESS = "粗心"
    UNKNOWN = "不会"
    MISUNDERSTOOD = "理解错"
    CALCULATION = "计算错"
    TIME = "时间不够"


class MasteryStatus(str, Enum):
    UNMASTERED = "未掌握"
    REVIEWING = "复习中"
    MASTERED = "已掌握"


class AnalysisStatus(str, Enum):
    NOT_ANALYZED = "未分析"
    ANALYZING = "分析中"
    COMPLETED = "已完成"
    FAILED = "失败"


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=4)
    content: str = Field(min_length=1, max_length=2000)


class QuestionCreate(BaseModel):
    exam_type: ExamType
    module: ExamModule
    stem: str = Field(min_length=1, max_length=20000)
    options: list[QuestionOption] = Field(default_factory=list, max_length=26)
    user_answer: str = Field(min_length=1, max_length=2000)
    correct_answer: str = Field(min_length=1, max_length=2000)
    original_explanation: str | None = Field(default=None, max_length=20000)
    source: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=20000)
    image_path: str | None = Field(default=None, max_length=1000)
    ocr_raw_text: str | None = Field(default=None, max_length=50000)
    knowledge_points: list[str] = Field(default_factory=list, max_length=100)
    error_reason: ErrorReason | None = None
    mastery_status: MasteryStatus = MasteryStatus.UNMASTERED
    analysis_status: AnalysisStatus = AnalysisStatus.NOT_ANALYZED
    tags: list[str] = Field(default_factory=list, max_length=100)


class QuestionUpdate(BaseModel):
    exam_type: ExamType | None = None
    module: ExamModule | None = None
    stem: str | None = Field(default=None, min_length=1, max_length=20000)
    options: list[QuestionOption] | None = Field(default=None, max_length=26)
    user_answer: str | None = Field(default=None, min_length=1, max_length=2000)
    correct_answer: str | None = Field(default=None, min_length=1, max_length=2000)
    original_explanation: str | None = Field(default=None, max_length=20000)
    source: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=20000)
    image_path: str | None = Field(default=None, max_length=1000)
    ocr_raw_text: str | None = Field(default=None, max_length=50000)
    knowledge_points: list[str] | None = Field(default=None, max_length=100)
    error_reason: ErrorReason | None = None
    mastery_status: MasteryStatus | None = None
    analysis_status: AnalysisStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=100)

    @field_validator(
        "exam_type",
        "module",
        "stem",
        "options",
        "user_answer",
        "correct_answer",
        "knowledge_points",
        "mastery_status",
        "analysis_status",
        "tags",
        mode="before",
    )
    @classmethod
    def reject_null_for_required_fields(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class QuestionRead(QuestionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    current_analysis_id: str | None = None
    created_at: datetime
    updated_at: datetime


class QuestionPage(Pagination):
    items: list[QuestionRead]


class BulkStatusRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    mastery_status: MasteryStatus


class BulkResult(BaseModel):
    updated: int | None = None
    deleted: int | None = None
    not_found: list[str]
