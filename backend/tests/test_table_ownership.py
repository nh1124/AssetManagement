"""Guard table ownership at ORM row construction sites.

Known exceptions fix the starting boundary as writes move to their owners.
Field mutation on loaded rows and raw SQL are invisible to this guard.
"""
from __future__ import annotations

import ast
from pathlib import Path

from app import models

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# The module responsible for a table's invariants. Rows in that table should be
# created here and nowhere else.
OWNERS: dict[str, str] = {
    "accounts": "services/ledger_service",
    "journal_entries": "services/ledger_service",
    "transactions": "services/ledger_service",
    "transaction_batches": "routers/quick_templates",
    "quick_templates": "routers/quick_templates",
    "registry_entries": "services/registry_service",
    "recurring_transactions": "services/registry_service",
    "budget_plans": "services/budget_plan_store",
    "monthly_plan_lines": "services/budget_plan_store",
    "monthly_actions": "services/action_bridge_service",
    "period_reviews": "routers/period_reviews",
    "capsules": "services/capsule_service",
    "capsule_rules": "services/capsule_service",
    "capsule_holdings": "services/capsule_service",
    "life_events": "routers/life_events",
    "milestones": "services/milestone_service",
    "simulation_configs": "routers/simulation",
    "simulation_scenarios": "routers/simulation_scenarios",
    "products": "routers/products",
    "exchange_rates": "services/fx_service",
    "ai_change_requests": "services/ai_change_request_service",
    "ai_audit_logs": "services/ai_policy_service",
    "ai_operation_policies": "services/ai_policy_service",
    "clients": "routers/auth",
    "client_mfa_settings": "services/mfa_service",
    "client_recovery_codes": "services/mfa_service",
}

# The import/export endpoint restores every table of a client from a payload, so
# it is the one module that is allowed to create rows anywhere.
WHOLE_DATABASE = "routers/data_transfer"

# Known writers that are not the owner. This is the starting point, not a target:
# each line is a boundary the redesign intends to close, and the test above fails
# if a new one appears. The reason says what would have to change to remove it.
ALLOWED: dict[str, dict[str, str]] = {
    "accounts": {
        "routers/accounts": "account CRUD predates ledger_service owning the table",
    },
    "budget_plans": {
        "routers/budget_plans": "plan CRUD lives in the router, not in budget_plan_store",
    },
    "capsules": {
        "routers/capsules": "capsule CRUD lives in the router",
        "services/product_reserve_service": "a product reserve creates its own capsule",
    },
    "capsule_rules": {
        "routers/capsules": "rule CRUD lives in the router",
    },
    "capsule_holdings": {
        "routers/capsules": "holding CRUD lives in the router",
    },
    "clients": {
        "main": "development seeding of the default client at startup",
    },
    "exchange_rates": {
        "routers/exchange_rates": "manual rate entry lives in the router",
    },
    "milestones": {
        "routers/roadmap": "milestone CRUD lives in the router",
    },
    "monthly_actions": {
        "services/report_service": "the monthly report proposes actions",
    },
    "monthly_plan_lines": {
        "routers/budget_plans": "plan line CRUD and batch edit live in the router",
        "services/action_bridge_service": "applying a set_budget action writes a line",
    },
    "registry_entries": {
        "routers/registry_entries": "registry CRUD lives in the router",
    },
    "transactions": {
        "routers/transactions": "E4 will move this to ledger_service.create_transaction",
        "routers/life_events": "E4",
        "routers/quick_templates": "E4",
        "services/recurring_service": "E4",
        "services/report_service": "E4",
        "services/ai_change_request_service": "E4",
    },
}


def _model_tables() -> dict[str, str]:
    return {
        name: value.__tablename__
        for name, value in vars(models).items()
        if isinstance(value, type) and hasattr(value, "__tablename__")
    }


def _constructions() -> set[tuple[str, str]]:
    tables = _model_tables()
    found: set[tuple[str, str]] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name == "models.py" or "__pycache__" in path.parts:
            continue
        module = path.relative_to(APP_DIR).with_suffix("").as_posix()
        # A BOM must not make a module invisible to the ownership guard.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imported: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            # Resolve relative imports to distinguish app.models from unrelated
            # modules with the same final name.
            parts = ["app", *module.split("/")[:-1]]
            if node.level:
                base = parts[:len(parts) - node.level + 1]
                target = ".".join(base + (node.module or "").split("."))
            else:
                target = node.module
            if target != "app.models":
                continue
            for alias in node.names:
                if alias.name == "*":
                    imported.update({name: name for name in tables})
                elif alias.name in tables:
                    imported[alias.asname or alias.name] = alias.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = None
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "models"
            ):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = imported.get(func.id)
            if name in tables:
                found.add((module, tables[name]))
    return found


def test_every_table_has_an_owner():
    tables = set(_model_tables().values())
    missing = sorted(tables - set(OWNERS))
    unknown = sorted(set(OWNERS) - tables)
    assert not missing and not unknown, (
        f"Tables without owners: {missing}\nOWNERS names nonexistent tables: {unknown}"
    )


def test_owner_modules_exist():
    modules = set(OWNERS.values()) | {WHOLE_DATABASE}
    modules.update(module for entries in ALLOWED.values() for module in entries)
    missing = sorted(module for module in modules if not (APP_DIR / f"{module}.py").is_file())
    assert not missing, "Ownership modules do not exist:\n" + "\n".join(missing)


def test_only_the_owner_or_a_listed_module_creates_rows():
    violations = [
        f"{module} creates {table} (owner: {OWNERS.get(table, '<unassigned>')})"
        for module, table in sorted(_constructions())
        if module != OWNERS.get(table)
        and module not in ALLOWED.get(table, {})
        and module != WHOLE_DATABASE
    ]
    assert not violations, "Unexpected table writers:\n" + "\n".join(violations)


def test_the_allowed_list_has_no_stale_entries():
    # Moving a write home must also close its former exception.
    observed = _constructions()
    stale = sorted(
        f"{module} no longer creates {table} (owner: {OWNERS.get(table, '<unassigned>')})"
        for table, entries in ALLOWED.items()
        for module in entries
        if (module, table) not in observed
    )
    assert not stale, "Stale ALLOWED entries:\n" + "\n".join(stale)
