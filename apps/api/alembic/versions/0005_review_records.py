"""Add review history and constrain daily review settings.

Revision ID: 0005_review_records
Revises: 0004_analysis_error_code
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_review_records"
down_revision: str | None = "0004_analysis_error_code"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.create_check_constraint(
            "ck_user_settings_daily_review_limit",
            "daily_review_limit IN (10, 20, 30, 50)",
        )
    op.create_table(
        "review_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("result_status", sa.String(length=20), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_records_question_id", "review_records", ["question_id"], unique=False
    )
    op.create_index(
        "ix_review_records_user_id", "review_records", ["user_id"], unique=False
    )
    op.create_index(
        "ix_review_records_user_reviewed_at",
        "review_records",
        ["user_id", "reviewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_review_records_user_reviewed_at", table_name="review_records")
    op.drop_index("ix_review_records_user_id", table_name="review_records")
    op.drop_index("ix_review_records_question_id", table_name="review_records")
    op.drop_table("review_records")
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.drop_constraint(
            "ck_user_settings_daily_review_limit", type_="check"
        )
