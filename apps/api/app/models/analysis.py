from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.question import Question


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    question_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    cause_analysis: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_points: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    correct_approach: Mapped[str] = mapped_column(Text, nullable=False)
    study_advice: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_error_reason: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    raw_response: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_demo: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    question: Mapped[Question] = relationship(
        "Question", back_populates="analyses", foreign_keys=[question_id]
    )
