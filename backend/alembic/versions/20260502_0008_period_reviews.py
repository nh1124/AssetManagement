"""period_reviews

Revision ID: 20260502_0008
Revises: 20260502_0007
Create Date: 2026-05-02 00:08:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260502_0008"
down_revision: Union[str, None] = "20260502_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "period_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(), nullable=False, server_default=""),
        sa.Column("reflection", sa.Text(), nullable=True),
        sa.Column("next_actions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "start_date", "end_date", name="_client_review_range_uc"),
    )
    op.create_index(op.f("ix_period_reviews_id"), "period_reviews", ["id"], unique=False)

    op.execute(
        """
        INSERT INTO period_reviews (
            client_id,
            start_date,
            end_date,
            label,
            reflection,
            next_actions,
            created_at,
            updated_at
        )
        SELECT
            client_id,
            to_date(target_period || '-01', 'YYYY-MM-DD') AS start_date,
            (to_date(target_period || '-01', 'YYYY-MM-DD') + interval '1 month - 1 day')::date AS end_date,
            target_period AS label,
            reflection,
            next_actions,
            created_at,
            updated_at
        FROM monthly_reviews
        WHERE target_period ~ '^[0-9]{4}-[0-9]{2}$'
        ON CONFLICT ON CONSTRAINT _client_review_range_uc DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_period_reviews_id"), table_name="period_reviews")
    op.drop_table("period_reviews")
