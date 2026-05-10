"""sync_legacy_constraints

Revision ID: 20260502_0004
Revises: 20260502_0003
Create Date: 2026-05-02 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260502_0004"
down_revision: Union[str, None] = "20260502_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '_goal_allocation_event_account_uc'
            ) THEN
                ALTER TABLE goal_allocations
                ADD CONSTRAINT _goal_allocation_event_account_uc
                UNIQUE (life_event_id, account_id);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'milestones_life_event_id_fkey'
            ) THEN
                ALTER TABLE milestones
                ADD CONSTRAINT milestones_life_event_id_fkey
                FOREIGN KEY (life_event_id)
                REFERENCES life_events(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Legacy sync only. The baseline schema already owns these constraints.
    pass
