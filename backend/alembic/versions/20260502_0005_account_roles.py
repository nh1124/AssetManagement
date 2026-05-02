"""account_roles

Revision ID: 20260502_0005
Revises: 20260502_0004
Create Date: 2026-05-02 00:05:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260502_0005"
down_revision: Union[str, None] = "20260502_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "role",
            sa.String(),
            nullable=False,
            server_default="unassigned",
        ),
    )
    op.add_column(
        "accounts",
        sa.Column("role_target_amount", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "role_target_amount")
    op.drop_column("accounts", "role")
