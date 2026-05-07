"""recurring_currency

Revision ID: 20260507_0021
Revises: 20260507_0020
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0021"
down_revision: Union[str, None] = "20260507_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recurring_transactions",
        sa.Column("currency", sa.String(), nullable=False, server_default="JPY"),
    )


def downgrade() -> None:
    op.drop_column("recurring_transactions", "currency")
