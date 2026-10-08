"""Structural guards for the service layer (P6-001).

These tests read the import graph statically instead of importing the modules,
so they catch a cycle even when it is hidden inside a function-local import --
which is exactly how the three historical cycles were being masked.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"

# accounting_service is a backwards-compatible facade that re-exports both
# halves of the module it was split from. Including it would report a false
# layering violation, since a facade sits above everything it re-exports.
EXCLUDED = {"__init__.py", "accounting_service.py"}

# Lower number = closer to the leaves. A module may import its own layer or any
# layer below it, never above. Same-layer imports are allowed because the
# acyclicity test already rejects the dangerous case.
LAYERS: dict[str, int] = {
    # L0 - leaves: no dependency on any other service
    "ai_policy_service": 0,
    "cache_service": 0,
    "fx_service": 0,
    "mfa_service": 0,
    "product_reserve_service": 0,
    "schedule_rules": 0,
    # L1 - the ledger itself
    "ledger_service": 1,
    # L2 - the source of truth for recurring cash flow, and its bucket model
    "capsule_service": 2,
    "registry_service": 2,
    # L3 - generated from the registry
    "budget_plan_service": 3,
    "recurring_service": 3,
    # L4 - statements and variance, which need the adopted plan
    "reporting_service": 4,
    # L5 - composition over everything below
    "action_bridge_service": 5,
    "ai_change_request_service": 5,
    "ai_context_service": 5,
    "analysis_service": 5,
    "data_health_service": 5,
    "goal_service": 5,
    "milestone_service": 5,
    "reconcile_service": 5,
    "report_service": 5,
    "simulation_service": 5,
    "strategy_service": 5,
}


def _service_modules() -> list[str]:
    return sorted(
        path.stem
        for path in SERVICES_DIR.glob("*.py")
        if path.name not in EXCLUDED
    )


def _imports_of(module: str, known: set[str]) -> set[str]:
    """Sibling service modules imported by `module`, at any nesting depth.

    Handles both spellings used in this codebase:
      from .registry_service import x          (level 1)
      from ..services.registry_service import x (level 2)
    """
    # utf-8-sig: at least one service module is stored with a BOM.
    source = (SERVICES_DIR / f"{module}.py").read_text(encoding="utf-8-sig")
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        name = None
        if node.level == 1:
            name = node.module
        elif node.level == 2 and node.module.startswith("services."):
            name = node.module.split(".", 1)[1]
        if name in known:
            found.add(name)
    found.discard(module)
    return found


def _build_graph() -> dict[str, set[str]]:
    modules = _service_modules()
    known = set(modules)
    return {module: _imports_of(module, known) for module in modules}


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """Return one import cycle as a path, or None when the graph is acyclic."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in graph}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = GREY
        stack.append(node)
        for dep in sorted(graph[node]):
            if colour[dep] == GREY:
                return stack[stack.index(dep):] + [dep]
            if colour[dep] == WHITE:
                cycle = visit(dep)
                if cycle:
                    return cycle
        stack.pop()
        colour[node] = BLACK
        return None

    for node in sorted(graph):
        if colour[node] == WHITE:
            cycle = visit(node)
            if cycle:
                return cycle
    return None


def test_every_service_module_is_assigned_a_layer():
    """A new service must be placed in the layering on purpose, not by accident."""
    unassigned = sorted(set(_service_modules()) - set(LAYERS))
    assert not unassigned, (
        "These service modules have no layer in LAYERS: "
        f"{unassigned}. Add them to backend/tests/test_service_layer_acyclic.py "
        "and decide where they belong."
    )


def test_service_imports_are_acyclic():
    """No import cycle, including ones hidden in function-local imports."""
    cycle = _find_cycle(_build_graph())
    assert cycle is None, "Import cycle in backend/app/services: " + " -> ".join(cycle)


def test_services_never_import_a_higher_layer():
    """registry is the source of truth; recurring, budget and reporting are downstream."""
    graph = _build_graph()
    violations = []
    for module, deps in sorted(graph.items()):
        if module not in LAYERS:
            continue
        for dep in sorted(deps):
            if dep in LAYERS and LAYERS[dep] > LAYERS[module]:
                violations.append(
                    f"{module} (L{LAYERS[module]}) imports {dep} (L{LAYERS[dep]})"
                )
    assert not violations, "Upward imports:\n  " + "\n  ".join(violations)


@pytest.mark.parametrize(
    "module, forbidden",
    [
        # The ledger is the foundation: it must stay free of every other service.
        ("ledger_service", None),
        # The registry is the source of truth, so it must not depend on the
        # artefacts generated from it.
        ("registry_service", {"recurring_service", "budget_plan_service"}),
        # Planning consumes the registry; it must not reach back into the goal
        # domain, which sits above it.
        ("budget_plan_service", {"goal_service", "strategy_service", "reporting_service"}),
    ],
)
def test_key_modules_keep_their_boundaries(module, forbidden):
    deps = _build_graph()[module]
    if forbidden is None:
        assert not deps, f"{module} must not import any other service, found: {sorted(deps)}"
    else:
        leaked = sorted(deps & forbidden)
        assert not leaked, f"{module} must not import {leaked}"
