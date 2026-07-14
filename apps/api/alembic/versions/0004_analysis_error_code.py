"""Add a stable public analysis failure code to questions.

Revision ID: 0004_analysis_error_code
Revises: 0003_uploaded_assets
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_analysis_error_code"
down_revision: str | None = "0003_uploaded_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("analysis_error_code", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "analysis_error_code")
