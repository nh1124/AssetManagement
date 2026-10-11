"""drop the stored plan-line recurring link

The column linked a budget line to the recurring definition it mirrored for
sync_status and recurring_amount. Registry entries replaced recurring as the
budget source, and P7-002 removed the last writer of this stored link. The API
still derives the definition id from the line's registry entry.

All 24 active lines with this column already carry the same id in source_id,
so removing the fallback changes no active identity_key. The two inactive
lines relying on it are outside the unique index and deduplication.

Downgrade restores the nullable column and SET NULL foreign key, but does not
restore its values.

Revision ID: 20261011_0047
Revises: 20261010_0046
Create Date: 2026-10-11
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261011_0047"
down_revision: Union[str, None] = "20261010_0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for index in sa.inspect(op.get_bind()).get_indexes("monthly_plan_lines"):
        if "recurring_transaction_id" in index["column_names"]:
            op.drop_index(index["name"], table_name="monthly_plan_lines")
    op.drop_constraint(
        "fk_monthly_plan_lines_recurring_transaction_id",
        "monthly_plan_lines",
        type_="foreignkey",
    )
    op.drop_column("monthly_plan_lines", "recurring_transaction_id")


def downgrade() -> None:
    op.add_column(
        "monthly_plan_lines",
        sa.Column("recurring_transaction_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_monthly_plan_lines_recurring_transaction_id",
        "monthly_plan_lines",
        "recurring_transactions",
        ["recurring_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )
