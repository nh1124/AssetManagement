"""milestone_sources

Revision ID: 20260502_0009
Revises: 20260502_0008
Create Date: 2026-05-02 00:09:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260502_0009"
down_revision: Union[str, None] = "20260502_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "milestones",
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
    )
    op.add_column("milestones", sa.Column("source_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("milestones", "source_snapshot")
    op.drop_column("milestones", "source")
