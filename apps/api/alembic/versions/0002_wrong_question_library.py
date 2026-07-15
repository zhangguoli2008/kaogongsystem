"""Create wrong-question library and analysis tables.

Revision ID: 0002_wrong_question_library
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_wrong_question_library"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("exam_type", sa.String(length=20), nullable=False),
        sa.Column("module", sa.String(length=20), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("user_answer", sa.Text(), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("original_explanation", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("image_path", sa.String(length=1000), nullable=True),
        sa.Column("ocr_raw_text", sa.Text(), nullable=True),
        sa.Column(
            "knowledge_points",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("error_reason", sa.String(length=20), nullable=True),
        sa.Column(
            "mastery_status",
            sa.String(length=20),
            server_default="未掌握",
            nullable=False,
        ),
        sa.Column(
            "analysis_status",
            sa.String(length=20),
            server_default="未分析",
            nullable=False,
        ),
        sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("current_analysis_id", sa.String(length=36), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questions_user_id", "questions", ["user_id"], unique=False)
    op.create_index(
        "ix_questions_user_created_at",
        "questions",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_questions_user_module", "questions", ["user_id", "module"], unique=False
    )
    op.create_index(
        "ix_questions_user_mastery_status",
        "questions",
        ["user_id", "mastery_status"],
        unique=False,
    )
    op.create_index(
        "ix_questions_current_analysis_id",
        "questions",
        ["current_analysis_id"],
        unique=False,
    )
    op.create_table(
        "analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("cause_analysis", sa.Text(), nullable=False),
        sa.Column(
            "knowledge_points",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("correct_approach", sa.Text(), nullable=False),
        sa.Column("study_advice", sa.Text(), nullable=False),
        sa.Column("suggested_error_reason", sa.String(length=20), nullable=True),
        sa.Column(
            "raw_response",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analyses_question_id", "analyses", ["question_id"], unique=False
    )
    op.create_index("ix_analyses_user_id", "analyses", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_analyses_user_id", table_name="analyses")
    op.drop_index("ix_analyses_question_id", table_name="analyses")
    op.drop_table("analyses")
    op.drop_index("ix_questions_current_analysis_id", table_name="questions")
    op.drop_index("ix_questions_user_mastery_status", table_name="questions")
    op.drop_index("ix_questions_user_module", table_name="questions")
    op.drop_index("ix_questions_user_created_at", table_name="questions")
    op.drop_index("ix_questions_user_id", table_name="questions")
    op.drop_table("questions")
