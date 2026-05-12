"""add budget_plans table and plan_id to monthly_plan_lines

Revision ID: 20260512_0031
Revises: 20260510_0030
Create Date: 2026-05-12
"""

import sqlalchemy as sa
from alembic import op


revision = "20260512_0031"
down_revision = "20260510_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_plans",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "name", name="_client_budget_plan_name_uc"),
    )
    op.create_index("ix_budget_plans_client_id", "budget_plans", ["client_id"])

    op.add_column(
        "monthly_plan_lines",
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("budget_plans.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_monthly_plan_lines_plan_id", "monthly_plan_lines", ["plan_id"])

    # Data migration: create a default "Baseline" plan for each client that has plan lines
    op.execute("""
        INSERT INTO budget_plans (client_id, name, is_default, sort_order, created_at, updated_at)
        SELECT DISTINCT client_id, 'Baseline', true, 0, NOW(), NOW()
        FROM monthly_plan_lines
        WHERE client_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    # Assign existing lines to their client's default plan
    op.execute("""
        UPDATE monthly_plan_lines
        SET plan_id = bp.id
        FROM budget_plans bp
        WHERE bp.client_id = monthly_plan_lines.client_id
          AND bp.is_default = true
          AND monthly_plan_lines.plan_id IS NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_monthly_plan_lines_plan_id", "monthly_plan_lines")
    op.drop_column("monthly_plan_lines", "plan_id")
    op.drop_index("ix_budget_plans_client_id", "budget_plans")
    op.drop_table("budget_plans")
