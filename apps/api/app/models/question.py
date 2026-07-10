from __future__ import annotations

from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Question(TimestampMixin, Base):
    __tablename__ = "questions"
    __table_args__ = (
        Index("ix_questions_user_created_at", "user_id", "created_at"),
        Index("ix_questions_user_module", "user_id", "module"),
        Index("ix_questions_user_mastery_status", "user_id", "mastery_status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    exam_type: Mapped[str] = mapped_column(String(20), nullable=False)
    module: Mapped[str] = mapped_column(String(20), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    original_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ocr_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_points: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    error_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mastery_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="未掌握", server_default="未掌握"
    )
    analysis_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="未分析", server_default="未分析"
    )
    tags: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    current_analysis_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
