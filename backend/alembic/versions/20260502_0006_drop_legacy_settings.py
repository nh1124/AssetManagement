"""drop_legacy_settings

Revision ID: 20260502_0006
Revises: 20260502_0005
Create Date: 2026-05-02 00:06:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260502_0006"
down_revision: Union[str, None] = "20260502_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("settings", if_exists=True)


def downgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("gemini_api_key", sa.String(), nullable=True),
        sa.Column("default_currency", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
    )
