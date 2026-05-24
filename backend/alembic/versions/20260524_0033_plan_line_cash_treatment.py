"""plan line cash treatment

Revision ID: 20260524_0033
Revises: 20260517_0032
Create Date: 2026-05-24
"""

import sqlalchemy as sa
from alembic import op


revision = "20260524_0033"
down_revision = "20260517_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monthly_plan_lines",
        sa.Column("cash_treatment", sa.String(), server_default="auto", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("monthly_plan_lines", "cash_treatment")
