"""record recurring transaction provenance

New recurring postings retain their definition without making provenance
mandatory for hand-entered transactions. Existing postings remain NULL because
their provenance is unknown. Deleting a definition preserves its postings.

Revision ID: 20261010_0045
Revises: 20261010_0044
Create Date: 2026-10-10
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_0045"
down_revision: Union[str, None] = "20261010_0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("recurring_transaction_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_recurring_transaction_id",
        "transactions",
        "recurring_transactions",
        ["recurring_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_transactions_recurring_transaction_id", "transactions", ["recurring_transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_recurring_transaction_id", table_name="transactions")
    op.drop_constraint("fk_transactions_recurring_transaction_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "recurring_transaction_id")
