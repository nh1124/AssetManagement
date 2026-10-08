"""journal legs and liability kind

Groundwork for compound journal entries (P7-001).

journal_entries becomes the only place that says which account a transaction
touched and in which direction, so it needs a per-leg memo ("own share",
"advance for A") and a stable order. It also needs indexes: every aggregation
is moving from transactions.from/to_account_id onto this table's join, and
the table had none beyond its primary key.

accounts.liability_kind takes over the one distinction the ledger type carried
that journal legs cannot express: a card settles on a monthly cycle, a loan
does not. Both look like liability -> asset in the legs.

Revision ID: 20261009_0041
Revises: 20261008_0040
Create Date: 2026-10-09
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_0041"
down_revision: Union[str, None] = "20261008_0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("journal_entries", sa.Column("memo", sa.String(), nullable=True))
    op.add_column("journal_entries", sa.Column("sort_order", sa.Integer(), nullable=True))
    op.create_index(
        "ix_journal_entries_transaction_id", "journal_entries", ["transaction_id"], unique=False
    )
    op.create_index("ix_journal_entries_account_id", "journal_entries", ["account_id"], unique=False)

    op.add_column("accounts", sa.Column("liability_kind", sa.String(), nullable=True))

    # Existing rows: the debit side comes first, which is how the posting code
    # has always written them.
    op.execute(
        """
        UPDATE journal_entries
        SET sort_order = CASE WHEN COALESCE(debit, 0) > 0 THEN 0 ELSE 1 END
        WHERE sort_order IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("accounts", "liability_kind")
    op.drop_index("ix_journal_entries_account_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_transaction_id", table_name="journal_entries")
    op.drop_column("journal_entries", "sort_order")
    op.drop_column("journal_entries", "memo")
