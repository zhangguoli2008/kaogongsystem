"""Add persistent idempotency records for question-split OCR."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_question_split_ocr"
down_revision: str | None = "0005_review_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("ocr_metadata", sa.JSON(), nullable=True),
    )
    op.create_table(
        "ocr_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_file_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("api_name", sa.String(length=100), nullable=False),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("pdf_page_number", sa.Integer(), nullable=False),
        sa.Column("parameter_version", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="processing",
            nullable=False,
        ),
        sa.Column("question_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("normalized_result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'succeeded', 'failed')",
            name="ck_ocr_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"], ["uploaded_assets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_ocr_tasks_source_file_id", "ocr_tasks", ["source_file_id"])
    op.create_index("ix_ocr_tasks_user_id", "ocr_tasks", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ocr_tasks_user_id", table_name="ocr_tasks")
    op.drop_index("ix_ocr_tasks_source_file_id", table_name="ocr_tasks")
    op.drop_table("ocr_tasks")
    op.drop_column("questions", "ocr_metadata")
