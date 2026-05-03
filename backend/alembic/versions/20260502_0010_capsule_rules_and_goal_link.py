"""capsule_rules_and_goal_link

Revision ID: 20260502_0010
Revises: 20260502_0009
Create Date: 2026-05-02 00:10:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260502_0010"
down_revision: Union[str, None] = "20260502_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("capsules", sa.Column("life_event_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "capsules_life_event_id_fkey",
        "capsules",
        "life_events",
        ["life_event_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "capsule_rules",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("capsule_id", sa.Integer(), sa.ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_type", sa.String(), nullable=False),
        sa.Column("trigger_category", sa.String(), nullable=True),
        sa.Column("trigger_description", sa.String(), nullable=True),
        sa.Column("source_mode", sa.String(), nullable=False, server_default="transaction_account"),
        sa.Column("source_account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("amount_type", sa.String(), nullable=False, server_default="fixed"),
        sa.Column("amount_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("capsule_rules")
    op.drop_constraint("capsules_life_event_id_fkey", "capsules", type_="foreignkey")
    op.drop_column("capsules", "life_event_id")
