"""startup_schema_cleanup

Revision ID: 20260502_0002
Revises: 20260502_0001
Create Date: 2026-05-02 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260502_0002"
down_revision: Union[str, None] = "20260502_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS budget_limit")
    op.execute("ALTER TABLE milestones ADD COLUMN IF NOT EXISTS life_event_id INTEGER")


def downgrade() -> None:
    # This revision records a legacy idempotent startup cleanup. The baseline
    # schema already includes milestones.life_event_id, so downgrade only moves
    # the Alembic version pointer back to the baseline.
    pass
