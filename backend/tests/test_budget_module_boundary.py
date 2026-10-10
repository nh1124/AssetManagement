"""The budget is one feature split across nine files.

This declared surface lists what it offers the rest of the application; the
guard makes adding to that surface a decision.
"""
from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# The nine modules the budget feature is split across. Inside the family they
# import each other freely -- the acyclicity test already rejects the dangerous
# case. This file is about what the rest of the application may reach for.
FAMILY = {
    "budget_actuals",
    "budget_context",
    "budget_credit_settlement",
    "budget_lines",
    "budget_plan_service",
    "budget_plan_store",
    "budget_projection",
    "budget_registry_lines",
    "budget_warnings",
}

# What the budget offers the rest of the application. Adding a name here is a
# decision about the feature's API, which is the point: the list is small, and a
# seventeenth entry has to be argued for rather than imported.
PUBLIC: dict[str, set[str]] = {
    "budget_context": {"BudgetContext"},
    "budget_plan_service": {"get_budget_summary"},
    "budget_plan_store": {
        "create_plan_lines",
        "get_or_create_default_plan",
        "replace_plan_lines_from_plan",
        "resolve_budget_plan_id",
        "set_default_budget_plan",
        "update_plan_lines",
    },
    "budget_projection": {
        "get_cash_flow_projection",
        "liquid_cash",
        "planned_cash_outflow_remaining",
    },
    "budget_lines": {
        "assign_plan_line_identity",
        "line_identity_key",
        "newest_line_key",
    },
    "budget_actuals": {"claimed_leg_ids", "LINE_SIDE"},
}

# Internal by design: the settlement, the registry-derived lines and the setup
# warnings are assembled by budget_plan_service, and nothing outside the family
# has ever needed them.
INTERNAL = {"budget_credit_settlement", "budget_registry_lines", "budget_warnings"}


def _family_imports() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = path.relative_to(APP_DIR).with_suffix("").as_posix()
        # A BOM must not make a module invisible to the boundary guard.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # Resolve relative imports so unrelated namesakes cannot count
                # as members of the budget family.
                parts = ["app", *module.split("/")[:-1]]
                if node.level:
                    base = parts[:len(parts) - node.level + 1]
                    target = ".".join(base + (node.module or "").split("."))
                else:
                    target = node.module or ""
                if target in {f"app.services.{name}" for name in FAMILY}:
                    for alias in node.names:
                        found.add((module, target.rsplit(".", 1)[-1], alias.name))
                elif target == "app.services":
                    for alias in node.names:
                        if alias.name in FAMILY:
                            found.add((module, alias.name, "<module>"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {f"app.services.{name}" for name in FAMILY}:
                        found.add((module, alias.name.rsplit(".", 1)[-1], "<module>"))
    return found


def _outside_imports() -> set[tuple[str, str, str]]:
    return {
        entry for entry in _family_imports()
        if entry[0].rsplit("/", 1)[-1] not in FAMILY
    }


def test_outside_modules_import_only_the_declared_surface():
    violations = [
        f"{module} imports {name} from {family}"
        for module, family, name in sorted(_outside_imports())
        if name not in PUBLIC.get(family, set())
    ]
    assert not violations, "Undeclared budget imports:\n" + "\n".join(violations)


def test_the_declared_surface_is_public():
    private = sorted(
        f"{module}.{name}"
        for module, names in PUBLIC.items()
        for name in names if name.startswith("_")
    )
    assert not private, "Private names in PUBLIC:\n" + "\n".join(private)


def test_every_declared_name_exists():
    missing = []
    for module in sorted(FAMILY):
        imported = import_module(f"app.services.{module}")
        missing.extend(
            f"{module}.{name}" for name in sorted(PUBLIC.get(module, set()))
            if not hasattr(imported, name)
        )
    assert not missing, "Declared budget names do not exist:\n" + "\n".join(missing)


def test_internal_modules_have_no_outside_importers():
    violations = [
        f"{module} imports {name} from {family}"
        for module, family, name in sorted(_outside_imports())
        if family in INTERNAL
    ]
    declared = sorted(INTERNAL & PUBLIC.keys())
    assert not violations and not declared, (
        "Internal budget imports:\n" + "\n".join(violations)
        + f"\nInternal modules in PUBLIC: {declared}"
    )


def test_the_family_apex_is_not_imported_inside_the_family():
    violations = [
        f"{module} imports {name} from {family}"
        for module, family, name in sorted(_family_imports())
        if module.rsplit("/", 1)[-1] in FAMILY and family == "budget_plan_service"
    ]
    assert not violations, "Budget apex imports inside the family:\n" + "\n".join(violations)
