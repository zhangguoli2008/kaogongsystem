from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OCRTask(TimestampMixin, Base):
    __tablename__ = "ocr_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'succeeded', 'failed')",
            name="ck_ocr_tasks_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("uploaded_assets.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    api_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parameter_version: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="processing", server_default="processing"
    )
    question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
