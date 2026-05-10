"""drop note and priority columns from monthly_plan_lines

Revision ID: 20260510_0030
Revises: 20260510_0029
Create Date: 2026-05-10
"""

import sqlalchemy as sa
from alembic import op


revision = "20260510_0030"
down_revision = "20260510_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("monthly_plan_lines", "note")
    op.drop_column("monthly_plan_lines", "priority")


def downgrade() -> None:
    op.add_column("monthly_plan_lines", sa.Column("priority", sa.Integer(), server_default="2", nullable=False))
    op.add_column("monthly_plan_lines", sa.Column("note", sa.Text(), nullable=True))
