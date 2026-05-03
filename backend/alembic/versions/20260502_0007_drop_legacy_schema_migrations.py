"""drop_legacy_schema_migrations

Revision ID: 20260502_0007
Revises: 20260502_0006
Create Date: 2026-05-02 00:07:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260502_0007"
down_revision: Union[str, None] = "20260502_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("schema_migrations", if_exists=True)


def downgrade() -> None:
    op.create_table(
        "schema_migrations",
        sa.Column("version", sa.String(length=255), primary_key=True, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
