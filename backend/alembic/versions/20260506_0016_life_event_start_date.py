"""life_event_start_date

Revision ID: 20260506_0016
Revises: 20260505_0015
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260506_0016"
down_revision: Union[str, None] = "20260505_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("life_events", sa.Column("start_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("life_events", "start_date")
