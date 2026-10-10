"""require registry ownership of recurring definitions

The registry is the only writer of recurring definitions. Refuse orphaned
financial data rather than altering it to fit the constraint. Registry entries
own their definitions, including during the import's bulk wipe.

Revision ID: 20261010_0046
Revises: 20261010_0045
Create Date: 2026-10-10
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_0046"
down_revision: Union[str, None] = "20261010_0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    predicates = {
        "null_source": "r.source_registry_entry_id IS NULL",
        "missing_source": (
            "r.source_registry_entry_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM registry_entries e WHERE e.id = r.source_registry_entry_id)"
        ),
    }
    counts = {}
    samples = {}
    for kind, predicate in predicates.items():
        counts[kind] = connection.execute(sa.text(
            f"SELECT COUNT(*) FROM recurring_transactions r WHERE {predicate}"
        )).scalar_one()
        samples[kind] = list(connection.execute(sa.text(
            f"SELECT r.id FROM recurring_transactions r WHERE {predicate} ORDER BY r.id LIMIT 5"
        )).scalars())
    if any(counts.values()):
        raise RuntimeError(
            "Cannot require registry ownership: "
            f"NULL sources={counts['null_source']} (ids={samples['null_source']}), "
            f"missing registry sources={counts['missing_source']} (ids={samples['missing_source']}). "
            "Run reconcile_registry_recurring_links for that client first."
        )

    op.alter_column("recurring_transactions", "source_registry_entry_id", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("recurring_transactions_source_registry_entry_id_fkey", "recurring_transactions", type_="foreignkey")
    op.create_foreign_key(
        "recurring_transactions_source_registry_entry_id_fkey",
        "recurring_transactions",
        "registry_entries",
        ["source_registry_entry_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("recurring_transactions_source_registry_entry_id_fkey", "recurring_transactions", type_="foreignkey")
    op.create_foreign_key(
        "recurring_transactions_source_registry_entry_id_fkey",
        "recurring_transactions",
        "registry_entries",
        ["source_registry_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("recurring_transactions", "source_registry_entry_id", existing_type=sa.Integer(), nullable=True)
