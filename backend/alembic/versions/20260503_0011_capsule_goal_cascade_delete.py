"""capsule_goal_cascade_delete

Change capsules.life_event_id FK from SET NULL to CASCADE so that
deleting a Goal (LifeEvent) also deletes all linked Capsules and CapsuleRules.

Revision ID: 20260503_0011
Revises: 20260502_0010
Create Date: 2026-05-03 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260503_0011"
down_revision: Union[str, None] = "20260502_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the existing SET NULL constraint and recreate as CASCADE
    op.drop_constraint("capsules_life_event_id_fkey", "capsules", type_="foreignkey")
    op.create_foreign_key(
        "capsules_life_event_id_fkey",
        "capsules",
        "life_events",
        ["life_event_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Revert to SET NULL
    op.drop_constraint("capsules_life_event_id_fkey", "capsules", type_="foreignkey")
    op.create_foreign_key(
        "capsules_life_event_id_fkey",
        "capsules",
        "life_events",
        ["life_event_id"],
        ["id"],
        ondelete="SET NULL",
    )
