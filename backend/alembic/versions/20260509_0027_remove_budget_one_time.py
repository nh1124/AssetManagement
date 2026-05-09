"""remove budget one-time plan marker

Revision ID: 20260509_0027
Revises: 20260508_0026
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260509_0027"
down_revision = "20260508_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE monthly_plan_lines SET source = 'manual' WHERE source = 'one_time'")
    op.drop_column("monthly_plan_lines", "planned_date")


def downgrade() -> None:
    op.add_column("monthly_plan_lines", sa.Column("planned_date", sa.Date(), nullable=True))
