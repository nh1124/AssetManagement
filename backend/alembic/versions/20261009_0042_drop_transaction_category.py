"""drop transaction category

transactions.category was a free-text label the specs described as
"recommended to match the account name" and deliberately not a foreign key
(FR-03-5, FR-03-7). Its purpose was to catch an AI's suggestion and to serve as
a search tag.

It served neither well. In the dev database it had drifted from the accounts it
was meant to mirror -- the profit and loss statement reported a line for an
inactive seed account because 7 transactions still carried its name -- and both
capsule auto-allocation rules were dead because they matched an account name
against this field. What the field reliably held was a duplicate of the
account's own name.

Everything that classified by it now reads the account on each journal leg, so
it is removed as a spec change. Sub-classification, where it is wanted, belongs
to Account.parent_id; a per-leg note belongs to journal_entries.memo.

Revision ID: 20261009_0042
Revises: 20261009_0041
Create Date: 2026-10-09
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_0042"
down_revision: Union[str, None] = "20261009_0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("transactions", "category")


def downgrade() -> None:
    # The column comes back empty: the labels it held are not reconstructible
    # from the ledger, which is the point of removing it.
    op.add_column("transactions", sa.Column("category", sa.String(), nullable=True))
