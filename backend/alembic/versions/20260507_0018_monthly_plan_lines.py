"""monthly_plan_lines

Revision ID: 20260507_0018
Revises: 20260506_0017
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0018"
down_revision: Union[str, None] = "20260506_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_plan_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("target_period", sa.String(), nullable=False),
        sa.Column("line_type", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False, server_default="manual"),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("source_account_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monthly_plan_lines_client_period",
        "monthly_plan_lines",
        ["client_id", "target_period"],
    )

    op.execute(
        """
        INSERT INTO monthly_plan_lines (
            client_id,
            target_period,
            line_type,
            target_type,
            account_id,
            name,
            amount,
            priority,
            is_active,
            created_at
        )
        SELECT
            mb.client_id,
            mb.target_period,
            'expense',
            'account',
            mb.account_id,
            a.name,
            mb.amount,
            2,
            TRUE,
            CURRENT_TIMESTAMP
        FROM monthly_budgets mb
        LEFT JOIN accounts a ON a.id = mb.account_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_monthly_plan_lines_client_period", table_name="monthly_plan_lines")
    op.drop_table("monthly_plan_lines")
