"""Scenario records for the default yield and inflation of some months (§8-11, 期間ごとの前提).

Revision ID: 20261021_0085
Revises: 20261021_0084
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0085"
down_revision = "20261021_0084"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scenario_assumption_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_period", sa.String(7), nullable=False),
        sa.Column("end_period", sa.String(7), nullable=True),
        sa.Column("annual_return", sa.Float(), nullable=True),
        sa.Column("inflation", sa.Float(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_scenario_assumption_periods_scenario_id", "scenario_assumption_periods", ["scenario_id"])


def downgrade():
    op.drop_index("ix_scenario_assumption_periods_scenario_id", table_name="scenario_assumption_periods")
    op.drop_table("scenario_assumption_periods")
