"""recurring_plan_sync

Revision ID: 20260507_0020
Revises: 20260507_0019
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0020"
down_revision: Union[str, None] = "20260507_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recurring_transactions", sa.Column("start_period", sa.String(), nullable=True))
    op.add_column("recurring_transactions", sa.Column("end_period", sa.String(), nullable=True))
    op.add_column(
        "recurring_transactions",
        sa.Column("auto_post", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "monthly_plan_lines",
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
    )
    op.add_column(
        "monthly_plan_lines",
        sa.Column("recurring_transaction_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_monthly_plan_lines_recurring_transaction_id",
        "monthly_plan_lines",
        "recurring_transactions",
        ["recurring_transaction_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_monthly_plan_lines_recurring_transaction_id", "monthly_plan_lines", type_="foreignkey")
    op.drop_column("monthly_plan_lines", "recurring_transaction_id")
    op.drop_column("monthly_plan_lines", "source")
    op.drop_column("recurring_transactions", "auto_post")
    op.drop_column("recurring_transactions", "end_period")
    op.drop_column("recurring_transactions", "start_period")
