"""Unify automatic transactions and move depreciation switches to products.

Revision ID: 20261019_0076
Revises: 20261019_0075
"""
from alembic import op
import sqlalchemy as sa

from app.domain.automatic_migration import migrate_automatic_data, REMOVED_FIELDS

revision = "20261019_0076"
down_revision = "20261019_0075"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    snapshot = {name: [dict(row) for row in bind.execute(sa.text(f"SELECT * FROM {name}")).mappings()]
                for name in ("registry_entries", "recurring_transactions", "products", "transactions")}
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("accounts", "monthly_actions", "ai_change_requests"):
        if name in tables:
            table = sa.Table(name, sa.MetaData(), autoload_with=bind)
            snapshot[name] = [dict(row) for row in bind.execute(table.select()).mappings()]
    counts = migrate_automatic_data(snapshot)
    for name, fields in (("monthly_actions", ("kind", "payload", "result", "target_id")),
                         ("ai_change_requests", ("resource", "target_ref", "input_payload", "before_snapshot", "after_snapshot", "diff", "precondition_hash", "status", "approved_by_client_id", "approved_at", "result"))):
        if name in tables:
            table = sa.Table(name, sa.MetaData(), autoload_with=bind)
            for row in snapshot[name]:
                bind.execute(table.update().where(table.c.id == row["id"]).values(**{key: row[key] for key in fields}))
    if "ai_operation_policies" in tables:
        bind.execute(sa.text("UPDATE ai_operation_policies SET resource='auto_transactions' WHERE resource='recurring_transactions'"))
    if "notifications" in tables:
        bind.execute(sa.text("DELETE FROM notifications WHERE kind='recording_due'"))
        bind.execute(sa.text("UPDATE notifications SET link='/ledger/auto' WHERE kind='unmatched' AND link='/ledger/unmatched'"))
    print(f"WP13 migration counts: {counts}")
    op.add_column("products", sa.Column("auto_depreciation", sa.Boolean(), nullable=False, server_default=sa.false()))
    additions = [sa.Column("kind", sa.String()), sa.Column("repeat_mode", sa.String()),
                 sa.Column("start_date", sa.Date()), sa.Column("end_date", sa.Date()),
                 sa.Column("repeat_count", sa.Integer()), sa.Column("next_due_date", sa.Date())]
    for column in additions:
        op.add_column("registry_entries", column)
    op.add_column("transactions", sa.Column("registry_entry_id", sa.Integer()))
    # Remove both directions before deleting product entries or the generated table.
    if bind.dialect.name == "postgresql":
        op.drop_constraint("fk_transactions_recurring_transaction_id", "transactions", type_="foreignkey")
        op.drop_constraint("registry_entries_source_recurring_transaction_id_fkey", "registry_entries", type_="foreignkey")
        op.drop_constraint("recurring_transactions_source_registry_entry_id_fkey", "recurring_transactions", type_="foreignkey")
    for product in snapshot["products"]:
        bind.execute(sa.text("UPDATE products SET auto_depreciation=:enabled WHERE id=:id"),
                     {"enabled": product["auto_depreciation"], "id": product["id"]})
    for row in snapshot["registry_entries"]:
        values = {key: row[key] for key in ("id", "kind", "repeat_mode", "start_date", "end_date", "repeat_count", "next_due_date", "is_active", "frequency", "day_of_month")}
        for key in ("start_date", "end_date", "next_due_date"):
            if isinstance(values[key], str):
                from datetime import date
                values[key] = date.fromisoformat(values[key][:10])
        bind.execute(sa.text("UPDATE registry_entries SET " + ", ".join(f"{key}=:{key}" for key in values if key != "id") + " WHERE id=:id"), values)
    for row in snapshot["transactions"]:
        bind.execute(sa.text("UPDATE transactions SET registry_entry_id=:entry WHERE id=:id"),
                     {"entry": row.get("registry_entry_id"), "id": row["id"]})
    # The remaining references disappear with their columns, before the table is removed.
    with op.batch_alter_table("transactions") as batch:
        batch.drop_index("ix_transactions_recurring_transaction_id")
        batch.drop_column("recurring_transaction_id")
        batch.create_foreign_key("fk_transactions_registry_entry_id", "registry_entries", ["registry_entry_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_transactions_registry_entry_id", ["registry_entry_id"])
    bind.execute(sa.text("DELETE FROM registry_entries WHERE kind IS NULL"))
    with op.batch_alter_table("registry_entries") as batch:
        for field in sorted(REMOVED_FIELDS):
            batch.drop_column(field)
        batch.alter_column("frequency", existing_type=sa.String(), nullable=True, server_default=None)
        batch.alter_column("day_of_month", existing_type=sa.Integer(), nullable=True, server_default=None)
        for field in ("kind", "repeat_mode", "start_date"):
            batch.alter_column(field, nullable=False)
    op.drop_table("recurring_transactions")


def downgrade():
    raise RuntimeError("WP13 removes the generated recurring copy; restore a pre-wave backup to roll back")
