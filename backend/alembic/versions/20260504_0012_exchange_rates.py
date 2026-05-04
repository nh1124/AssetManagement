"""exchange_rates

Revision ID: 20260504_0012
Revises: 20260503_0011
Create Date: 2026-05-04 00:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260504_0012"
down_revision: Union[str, None] = "20260503_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("base_currency", sa.String(), nullable=False),
        sa.Column("quote_currency", sa.String(), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(), server_default="manual", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_id",
            "base_currency",
            "quote_currency",
            "as_of_date",
            name="_client_fx_rate_date_uc",
        ),
    )
    op.create_index(op.f("ix_exchange_rates_id"), "exchange_rates", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_exchange_rates_id"), table_name="exchange_rates")
    op.drop_table("exchange_rates")
