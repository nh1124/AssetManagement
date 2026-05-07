"""drop_monthly_budgets

Revision ID: 20260507_0019
Revises: 20260507_0018
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0019"
down_revision: Union[str, None] = "20260507_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("monthly_budgets")


def downgrade() -> None:
    op.create_table(
        "monthly_budgets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("target_period", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "target_period", name="_account_period_uc"),
    )
