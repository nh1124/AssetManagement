"""drop goal_allocations table

Revision ID: 20260505_0015
Revises: 20260505_0014
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = "20260505_0015"
down_revision = "20260505_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_goal_allocations_id", table_name="goal_allocations", if_exists=True)
    op.drop_constraint("_goal_allocation_event_account_uc", "goal_allocations", type_="unique", if_exists=True)
    op.drop_table("goal_allocations")


def downgrade():
    op.create_table(
        "goal_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("life_event_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("allocation_percentage", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["life_event_id"], ["life_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("life_event_id", "account_id", name="_goal_allocation_event_account_uc"),
    )
    op.create_index("ix_goal_allocations_id", "goal_allocations", ["id"])
