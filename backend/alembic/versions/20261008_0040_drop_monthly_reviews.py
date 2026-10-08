"""drop_monthly_reviews

PeriodReview superseded MonthlyReview in 20260502_0008, which copied the rows
across. The UI has read period_reviews ever since; monthly_reviews kept its
router, model, MCP tool and export entry without a single reader.

Revision ID: 20261008_0040
Revises: 20260606_0039
Create Date: 2026-10-08
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261008_0040"
down_revision: Union[str, None] = "20260606_0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("monthly_reviews")


def downgrade() -> None:
    op.create_table(
        "monthly_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("target_period", sa.String(), nullable=False),
        sa.Column("reflection", sa.Text(), nullable=True),
        sa.Column("next_actions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "target_period", name="_client_review_period_uc"),
    )
    op.create_index(op.f("ix_monthly_reviews_id"), "monthly_reviews", ["id"], unique=False)
