"""Which database role may do what (WP32 W5).

Three login roles share one database:

- ``am_owner`` owns every table and sequence. Only migrations connect as it
  (the ``migrate`` service), so DDL never runs from an application process.
- ``am_user_app`` is the user backend (``app.main``; the MCP server reaches the
  data only through it).
- ``am_admin_app`` is the admin backend and the admin CLI (``app.admin``).

The matrix below is the single source of truth; ``app.maintenance.db_grants``
turns it into GRANT statements and ``tests/test_db_access.py`` fails when a
table is missing from it. The point of the split: a compromised user backend
cannot read or write the administrators, their sessions, the audit log or the
installation settings, and cannot suspend, approve or un-suspend accounts.
"""
from __future__ import annotations

OWNER = "am_owner"
USER_APP = "am_user_app"
ADMIN_APP = "am_admin_app"
APP_ROLES = (USER_APP, ADMIN_APP)

READ = frozenset({"SELECT"})
FULL = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})

# The client columns the user side writes: profile, settings, sign-in state.
# Never is_active, approval_pending or suspended_reason (the administrator's).
CLIENT_COLUMNS_USER_UPDATES = (
    "name", "email", "password_hash", "general_settings", "must_change_password",
    "tokens_valid_after", "failed_login_count", "locked_until", "updated_at",
)

ADMIN_TABLES = ("admin_users", "admin_user_permissions", "admin_sessions")
AUTH_TABLES = ("client_mfa_settings", "client_recovery_codes")

USER_DATA_TABLES = (
    "accounts", "journal_entries", "transactions", "transaction_proposals", "transaction_batches",
    "registry_entries", "budget_plans", "monthly_plan_lines", "period_reviews",
    "capsules", "capsule_drawdowns", "capsule_rules", "capsule_funding_sources",
    "life_events", "life_event_conditions", "household_members", "life_scenarios",
    "scenario_contribution_plans", "scenario_assumption_periods", "goal_budget_reflections",
    "notifications", "life_event_links", "simulation_configs", "products", "product_depreciations",
    "exchange_rates", "fx_tracked_currencies", "ai_change_requests", "ai_audit_logs", "ai_operation_policies",
)

# What the administrator's data-health repair rewrites (repair_data_health).
ADMIN_REPAIR_WRITES = {
    "budget_plans": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "monthly_plan_lines": frozenset({"SELECT", "UPDATE"}),
}


def _build() -> dict[str, dict[str, frozenset[str]]]:
    access: dict[str, dict[str, frozenset[str]]] = {}
    for table in USER_DATA_TABLES:
        access[table] = {USER_APP: FULL, ADMIN_APP: ADMIN_REPAIR_WRITES.get(table, READ)}
    # Sign-up inserts; the user side updates only CLIENT_COLUMNS_USER_UPDATES (granted per column).
    access["clients"] = {USER_APP: frozenset({"SELECT", "INSERT"}),
                         ADMIN_APP: frozenset({"SELECT", "INSERT", "UPDATE"})}
    for table in AUTH_TABLES:
        # The administrator's MFA reset removes a client's factor; it never writes one.
        access[table] = {USER_APP: FULL, ADMIN_APP: frozenset({"SELECT", "DELETE"})}
    for table in ADMIN_TABLES:
        access[table] = {ADMIN_APP: FULL}
    # Append-only for everyone but the owner.
    access["admin_audit_logs"] = {ADMIN_APP: frozenset({"SELECT", "INSERT"})}
    access["system_settings"] = {USER_APP: READ, ADMIN_APP: frozenset({"SELECT", "INSERT", "UPDATE"})}
    return access


TABLE_ACCESS: dict[str, dict[str, frozenset[str]]] = _build()

# Column-level UPDATE grants (table, role) -> columns, in addition to TABLE_ACCESS.
COLUMN_UPDATES: dict[tuple[str, str], tuple[str, ...]] = {
    ("clients", USER_APP): CLIENT_COLUMNS_USER_UPDATES,
}

# Tables outside the models: the migrations' version table. Only am_owner writes
# it; a backup's manifest records the schema revision, so both applications read it.
NON_MODEL_TABLES: dict[str, dict[str, frozenset[str]]] = {
    "alembic_version": {USER_APP: READ, ADMIN_APP: READ},
}


def privileges(table: str, role: str) -> frozenset[str]:
    return {**NON_MODEL_TABLES, **TABLE_ACCESS}.get(table, {}).get(role, frozenset())


def can_write(table: str, role: str) -> bool:
    return bool(privileges(table, role) & {"INSERT", "UPDATE", "DELETE"}) or (table, role) in COLUMN_UPDATES
