"""AI permissions per operation (owner 2026-10-24, WP36 C8-C10).

ai_operation_policies keyed by (resource, action, risk, AI client) with amount and
count thresholds and a per-rule MFA flag becomes one row per operation of
domain/ai_operations (client, operation, mode: allow / approval / deny). The rows
that took effect before are carried over so nothing the AI could or could not do
changes:

- transactions / create was the shared gate of every direct ledger write, so it
  becomes a row for each operation that posts to the ledger: allow if it allowed
  direct writes (allow_execute without MFA), otherwise approval for recording a
  transaction (a change request) and deny for the others (they had no approval path);
- the change-request operations and the AI context read keep their mode;
- any other row never took effect and is dropped.

Approval now always asks for the authenticator code, so ai_change_requests.requires_mfa
goes; so do the unused AI-client columns of the change requests and the audit log.

Revision ID: 20261024_0094
Revises: 20261024_0093
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20261024_0094"
down_revision = "20261024_0093"
branch_labels = None
depends_on = None

# domain/ai_operations at this revision: the operations that post journal entries.
LEDGER_OPERATIONS = (
    "transactions.create", "transactions.update", "transactions.delete", "transaction_batches.create",
    "accounts.reconcile_adjust", "capsules.contribute", "capsules.drawdown", "capsules.account_claim",
    "depreciations.record", "depreciations.amend",
)
CHANGE_REQUEST_OPERATIONS = {
    ("auto_transactions", "create"): "auto_transactions.create",
    ("auto_transactions", "update"): "auto_transactions.update",
    ("monthly_plan_lines", "update"): "plan_lines.update",
}
_RISK_ORDER = {"medium": 0, "low": 1, "high": 2, "critical": 3}


def carried_over(rows) -> dict[tuple[int, str], str]:
    """The new (client, operation) -> mode rows for the old policy rows that took effect."""
    result: dict[tuple[int, str], str] = {}
    # When a client had several risks of one rule, the medium one is what the gates read.
    ordered = sorted(rows, key=lambda row: _RISK_ORDER.get(row.risk, 9), reverse=True)
    for row in ordered:
        key = (row.resource, row.action)
        direct = row.mode == "allow_execute" and not row.require_mfa
        if key == ("transactions", "create"):
            for operation in LEDGER_OPERATIONS:
                if direct:
                    mode = "allow"
                elif operation == "transactions.create" and row.mode in {"allow_execute", "require_approval"}:
                    mode = "approval"
                else:
                    mode = "deny"
                result[(row.client_id, operation)] = mode
        elif key in CHANGE_REQUEST_OPERATIONS:
            mode = ("allow" if row.mode == "allow_execute"
                    else "approval" if row.mode == "require_approval" else "deny")
            result[(row.client_id, CHANGE_REQUEST_OPERATIONS[key])] = mode
        elif key == ("ai_context", "read"):
            result[(row.client_id, "ai_context.read")] = "deny" if row.mode == "deny" else "allow"
    return result


def upgrade():
    bind = op.get_bind()
    old = bind.execute(sa.text(
        "SELECT client_id, resource, action, risk, mode, require_mfa FROM ai_operation_policies"
    )).fetchall()
    new = carried_over(old)
    bind.execute(sa.text("DELETE FROM ai_operation_policies"))

    op.drop_index("ix_ai_operation_policies_ai_client_id", table_name="ai_operation_policies")
    with op.batch_alter_table("ai_operation_policies") as batch:
        batch.drop_constraint("_client_ai_policy_uc", type_="unique")
        for column in ("ai_client_id", "resource", "action", "risk", "threshold_amount_minor", "threshold_count", "require_mfa"):
            batch.drop_column(column)
        batch.add_column(sa.Column("operation", sa.String(), nullable=False))
        batch.create_unique_constraint("_client_ai_operation_uc", ["client_id", "operation"])

    now = datetime.utcnow()
    policies = sa.table(
        "ai_operation_policies",
        sa.column("client_id", sa.Integer), sa.column("operation", sa.String), sa.column("mode", sa.String),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    if new:
        op.bulk_insert(policies, [
            {"client_id": client_id, "operation": operation, "mode": mode, "created_at": now, "updated_at": now}
            for (client_id, operation), mode in sorted(new.items())
        ])
    print(f"WP36 migration counts: {{'old_rules': {len(old)}, 'operation_rows': {len(new)}}}")

    op.drop_index("ix_ai_change_requests_ai_client_id", table_name="ai_change_requests")
    with op.batch_alter_table("ai_change_requests") as batch:
        batch.drop_column("ai_client_id")
        batch.drop_column("requires_mfa")
    op.drop_index("ix_ai_audit_logs_ai_client_id", table_name="ai_audit_logs")
    with op.batch_alter_table("ai_audit_logs") as batch:
        batch.drop_column("ai_client_id")


def _client_fk(table: str) -> sa.ForeignKey:
    # Named as PostgreSQL names them, so a batch rebuild on SQLite can carry them too.
    return sa.ForeignKey("clients.id", name=f"{table}_ai_client_id_fkey")


def downgrade():
    with op.batch_alter_table("ai_audit_logs") as batch:
        batch.add_column(sa.Column("ai_client_id", sa.Integer(), _client_fk("ai_audit_logs"), nullable=True))
    op.create_index("ix_ai_audit_logs_ai_client_id", "ai_audit_logs", ["ai_client_id"])
    with op.batch_alter_table("ai_change_requests") as batch:
        batch.add_column(sa.Column("ai_client_id", sa.Integer(), _client_fk("ai_change_requests"), nullable=True))
        batch.add_column(sa.Column("requires_mfa", sa.Boolean(), server_default="false", nullable=False))
    op.create_index("ix_ai_change_requests_ai_client_id", "ai_change_requests", ["ai_client_id"])

    bind = op.get_bind()
    # Only the shared ledger gate maps back; the other operations had no rule of their own.
    allowed = [row.client_id for row in bind.execute(sa.text(
        "SELECT client_id FROM ai_operation_policies WHERE operation = 'transactions.create' AND mode = 'allow'"
    )).fetchall()]
    bind.execute(sa.text("DELETE FROM ai_operation_policies"))
    with op.batch_alter_table("ai_operation_policies") as batch:
        batch.drop_constraint("_client_ai_operation_uc", type_="unique")
        batch.drop_column("operation")
        batch.add_column(sa.Column("ai_client_id", sa.Integer(), _client_fk("ai_operation_policies"), nullable=True))
        batch.add_column(sa.Column("resource", sa.String(), nullable=False))
        batch.add_column(sa.Column("action", sa.String(), nullable=False))
        batch.add_column(sa.Column("risk", sa.String(), nullable=False))
        batch.add_column(sa.Column("threshold_amount_minor", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("threshold_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("require_mfa", sa.Boolean(), server_default="false", nullable=False))
        batch.create_unique_constraint("_client_ai_policy_uc", ["client_id", "ai_client_id", "resource", "action", "risk"])
    op.create_index("ix_ai_operation_policies_ai_client_id", "ai_operation_policies", ["ai_client_id"])
    now = datetime.utcnow()
    for client_id in allowed:
        bind.execute(sa.text(
            "INSERT INTO ai_operation_policies (client_id, resource, action, risk, mode, require_mfa, created_at, updated_at) "
            "VALUES (:client_id, 'transactions', 'create', 'medium', 'allow_execute', false, :now, :now)"
        ), {"client_id": client_id, "now": now})
