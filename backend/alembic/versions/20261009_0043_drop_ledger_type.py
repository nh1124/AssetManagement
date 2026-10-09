"""drop ledger type

Each of the seven transaction types stood for a pair of account types: Expense
was asset -> expense, CreditExpense liability -> expense, and so on. Only
Borrowing and CreditAssetPurchase shared a pair, and the dev database holds no
Borrowing row at all, so the names carried nothing the legs do not say.

Keeping them was worse than redundant. The value could disagree with the
accounts -- seven card charges were typed Expense and so were invisible to the
settlement projection -- and a whole MCP tool existed to help an agent pick
one. The one distinction that was real, whether a liability settles on a
monthly cycle, moved to accounts.liability_kind in 20261009_0041.

Dropped here: transactions.type, recurring_transactions.type, and
registry_entries.transaction_type. registry_entries.line_type stays: it is the
budget's own vocabulary, not the ledger's, and 53 of 68 entries carry a
line_type that disagrees with the ledger type they also carried.

Revision ID: 20261009_0043
Revises: 20261009_0042
Create Date: 2026-10-09
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_0043"
down_revision: Union[str, None] = "20261009_0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("transactions", "type")
    op.drop_column("recurring_transactions", "type")
    op.drop_column("registry_entries", "transaction_type")


def downgrade() -> None:
    # The columns come back with the default every row would have been given
    # anyway. The original values are not reconstructible for the one pair the
    # legs cannot tell apart, but no row in this database used it.
    op.add_column("registry_entries", sa.Column("transaction_type", sa.String(), nullable=False, server_default="Expense"))
    op.add_column("recurring_transactions", sa.Column("type", sa.String(), nullable=True))
    op.add_column("transactions", sa.Column("type", sa.String(), nullable=True))
