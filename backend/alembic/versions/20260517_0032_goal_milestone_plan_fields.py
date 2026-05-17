"""goal milestone plan fields

Revision ID: 20260517_0032
Revises: 20260512_0031
Create Date: 2026-05-17
"""

import sqlalchemy as sa
from alembic import op


revision = "20260517_0032"
down_revision = "20260512_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "life_events",
        sa.Column("active_plan_basis", sa.String(), server_default="milestone", nullable=False),
    )
    op.add_column("life_events", sa.Column("active_plan_label", sa.String(), nullable=True))
    op.add_column("life_events", sa.Column("plan_status_override", sa.String(), nullable=True))
    op.add_column(
        "milestones",
        sa.Column("is_active_plan", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("milestones", "is_active_plan")
    op.drop_column("life_events", "plan_status_override")
    op.drop_column("life_events", "active_plan_label")
    op.drop_column("life_events", "active_plan_basis")
