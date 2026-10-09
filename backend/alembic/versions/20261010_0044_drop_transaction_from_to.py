"""drop the transaction from/to columns

The pair was a summary of the legs: from_account_id the account on the sole
credit leg, to_account_id the one on the sole debit leg. Two ways it could
lie. It could disagree with the legs, because nothing recomputed it when the
entries were rewritten by hand or by an older code path; and for a compound
entry there is no single account on a side, so the honest value was NULL and
readers that trusted the columns saw a transaction that touched nothing.

Both stay in the API. They are accepted as input -- the ordinary two-sided
entry is still written as a from/to pair, which ledger_service.simple_legs
turns into two legs -- and they are still reported, derived per row by
services.journal_legs.primary_accounts. What goes is the stored copy.

Revision ID: 20261010_0044
Revises: 20261009_0043
Create Date: 2026-10-10
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_0044"
down_revision: Union[str, None] = "20261009_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("transactions", "from_account_id")
    op.drop_column("transactions", "to_account_id")


def downgrade() -> None:
    # The values come back from the legs, which is where they came from in the
    # first place: the sole credit leg is from, the sole debit leg is to, and a
    # compound entry keeps the NULL it had.
    op.add_column("transactions", sa.Column("from_account_id", sa.Integer(), nullable=True))
    op.add_column("transactions", sa.Column("to_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "transactions_from_account_id_fkey", "transactions", "accounts", ["from_account_id"], ["id"]
    )
    op.create_foreign_key(
        "transactions_to_account_id_fkey", "transactions", "accounts", ["to_account_id"], ["id"]
    )
    op.execute(
        """
        UPDATE transactions t
        SET from_account_id = sole.account_id
        FROM (
            SELECT transaction_id, MIN(account_id) AS account_id
            FROM journal_entries
            WHERE COALESCE(credit, 0) > 0
            GROUP BY transaction_id
            HAVING COUNT(*) = 1
        ) AS sole
        WHERE sole.transaction_id = t.id
        """
    )
    op.execute(
        """
        UPDATE transactions t
        SET to_account_id = sole.account_id
        FROM (
            SELECT transaction_id, MIN(account_id) AS account_id
            FROM journal_entries
            WHERE COALESCE(debit, 0) > 0
            GROUP BY transaction_id
            HAVING COUNT(*) = 1
        ) AS sole
        WHERE sole.transaction_id = t.id
        """
    )
