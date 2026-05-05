"""capsule_holdings

Add capsule_holdings table to track which real-world accounts
physically hold the funds earmarked for each capsule.

Revision ID: 20260505_0013
Revises: 20260504_0012
Create Date: 2026-05-05 00:00:00
"""

from __future__ import annotations
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "20260505_0013"
down_revision: Union[str, None] = "20260504_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capsule_holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("capsule_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("held_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["capsule_id"], ["capsules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_capsule_holdings_capsule_id", "capsule_holdings", ["capsule_id"])


def downgrade() -> None:
    op.drop_index("ix_capsule_holdings_capsule_id", table_name="capsule_holdings")
    op.drop_table("capsule_holdings")
