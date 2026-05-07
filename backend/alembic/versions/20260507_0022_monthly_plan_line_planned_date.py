"""monthly_plan_line_planned_date

Revision ID: 20260507_0022
Revises: 20260507_0021
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0022"
down_revision: Union[str, None] = "20260507_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monthly_plan_lines", sa.Column("planned_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("monthly_plan_lines", "planned_date")
