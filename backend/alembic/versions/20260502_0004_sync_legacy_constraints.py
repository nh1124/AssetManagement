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
            ALTER TABLE goal_allocations
            ADD CONSTRAINT _goal_allocation_event_account_uc
            UNIQUE (life_event_id, account_id);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE milestones
            ADD CONSTRAINT milestones_life_event_id_fkey
            FOREIGN KEY (life_event_id)
            REFERENCES life_events(id)
            ON DELETE CASCADE;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    # Legacy sync only. The baseline schema already owns these constraints.
    pass
