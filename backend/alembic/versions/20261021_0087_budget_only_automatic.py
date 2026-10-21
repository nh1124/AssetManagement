"""自動取引 that only budget, and named manual plan records (WP27).

registry_entries.records_transactions (取引も記録する): false for an automatic transaction that only
budgets each month and never posts. A manual plan row's identity now includes its name, so one
section of an account may hold several of the user's records (one per reason): existing manual
rows get their identity key again in the new shape.

Revision ID: 20261021_0087
Revises: 20261021_0086
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "20261021_0087"
down_revision = "20261021_0086"
branch_labels = None
depends_on = None


def _key(row, with_name: bool) -> str:
    name = (row.name or "").strip().lower() if with_name or not (row.account_id or row.target_id) else ""
    return json.dumps([row.plan_id or 0, row.target_period, row.source_kind, row.line_type, row.target_type or "manual",
                       row.account_id or 0, row.source_account_id or 0, row.target_id or 0, name, row.cash_treatment or "auto"],
                      ensure_ascii=True, separators=(",", ":"))


def _rekey(with_name: bool) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, plan_id, target_period, source_kind, line_type, target_type, account_id, source_account_id, target_id, name, cash_treatment"
        " FROM monthly_plan_lines WHERE source_kind = 'manual'")).all()
    for row in rows:
        bind.execute(sa.text("UPDATE monthly_plan_lines SET identity_key = :key WHERE id = :id"), {"key": _key(row, with_name), "id": row.id})


def upgrade():
    with op.batch_alter_table("registry_entries") as batch:
        batch.add_column(sa.Column("records_transactions", sa.Boolean(), nullable=False, server_default=sa.true()))
    _rekey(True)


def downgrade():
    _rekey(False)
    with op.batch_alter_table("registry_entries") as batch:
        batch.drop_column("records_transactions")
