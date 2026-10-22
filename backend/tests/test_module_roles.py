"""Enforce the UI -> workflow -> service boundary, rather than describe it.

UI owns screens and HTTP adaptation; workflow receives a UI request and composes
the feature; service owns primitive database operations. UI and workflow may
neither access data nor construct models. D8 keeps transaction boundaries in
workflows because routers cannot close them: commit, rollback, refresh, flush,
expire and expire_all remain allowed there. Known violations are wave-specific
exceptions. A router can still hold business logic without touching its session;
that judgement cannot be made by this test.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys

import pytest

from app import models

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# A new directory needs an explicit role before its modules cross the boundary.
ROLE_BY_DIRECTORY: dict[str, str] = {
    "models": "model",
    "routers": "ui",
    "workflows": "workflow",
    "services": "service",
    # Pure domain vocabulary owns no tables and accepts no database sessions.
    "domain": "domain",
    "maintenance": "tool",
    "admin": "ui",
    "utils": "infra",
}

ROLE_BY_MODULE: dict[str, str] = {
    "main": "infra",
    "database": "infra",
    "dependencies": "infra",
    "config": "infra",
    "security": "infra",
    "schemas": "schema",
}

ALLOWED: dict[str, str] = {}

SESSION_METHODS = {
    "query", "add", "add_all", "delete", "commit", "flush", "refresh", "get",
    "execute", "merge", "rollback", "expire", "expire_all", "no_autoflush",
}

# commit, rollback, refresh and flush are the transaction boundary, which D8
# leaves with the workflow because a router cannot close one. flush belongs
# here rather than with data access: this codebase pairs it with commit in the
# `commit: bool = True` idiom, where it means "make the services' work visible
# without closing", and it decides nothing about which rows exist.
BOUNDARY_METHODS = {"commit", "rollback", "refresh", "flush", "expire", "expire_all"}
WORKFLOW_ALLOWED: dict[str, str] = {}

# C1 preserves existing service/workflow responses; later waves convert one
# module at a time. Counts prevent a listed module from accumulating more debt.
HTTP_EXCEPTION_ALLOWED: dict[str, int] = {}


def _role(module: str) -> str | None:
    if "/" in module:
        return ROLE_BY_DIRECTORY.get(module.split("/", 1)[0])
    return ROLE_BY_MODULE.get(module)


def _import_target(node: ast.ImportFrom, module: str) -> str:
    if not node.level:
        return node.module or ""
    parts = ["app", *module.split("/")[:-1]]
    base = parts[:len(parts) - node.level + 1]
    return ".".join(base + (node.module.split(".") if node.module else []))


def _reference(node: ast.AST, bindings: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return bindings.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return f"{_reference(node.value, bindings)}.{node.attr}"
    return ""


def _scope_nodes(node: ast.AST):
    yield node
    for child in ast.iter_child_nodes(node):
        # Nested functions receive their own aliases; unrelated locals must not
        # become sessions merely because another function uses the same name.
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _scope_nodes(child)


class _DatabaseUses(ast.NodeVisitor):
    def __init__(self, bindings: dict[str, str], model_names: set[str]):
        self.bindings = bindings
        self.model_names = model_names
        self.sessions = {"db", "session"}
        self.methods: set[str] = set()
        self.models: set[str] = set()

    def _visit_scope(self, node: ast.AST, arguments: ast.arguments | None = None):
        outer = self.sessions
        self.sessions = outer.copy()
        if arguments is not None:
            args = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
            defaults = [None] * (len(arguments.posonlyargs) + len(arguments.args) - len(arguments.defaults))
            defaults += [*arguments.defaults, *arguments.kw_defaults]
            for arg, default in zip(args, defaults):
                annotation = arg.annotation
                if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
                    annotation = ast.parse(annotation.value, mode="eval").body
                typed_session = annotation is not None and any(
                    _reference(part, self.bindings) in {"sqlalchemy.orm.Session", "sqlalchemy.orm.session.Session"}
                    for part in ast.walk(annotation)
                )
                session_dependency = (
                    isinstance(default, ast.Call) and default.args
                    and _reference(default.args[0], self.bindings) == "app.database.get_db"
                )
                if typed_session or session_dependency:
                    self.sessions.add(arg.arg)
        assignments = [part for part in _scope_nodes(node) if isinstance(part, (ast.Assign, ast.AnnAssign, ast.NamedExpr))]
        # Follow aliases to a fixed point so source ordering cannot hide a use.
        while True:
            before = self.sessions.copy()
            for assignment in assignments:
                value = assignment.value
                if isinstance(value, ast.Name) and value.id in self.sessions:
                    targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                    self.sessions.update(target.id for target in targets if isinstance(target, ast.Name))
            if self.sessions == before:
                break
        self.generic_visit(node)
        self.sessions = outer

    def visit_Module(self, node: ast.Module):
        self._visit_scope(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_scope(node, node.args)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda):
        self._visit_scope(node, node.args)

    def visit_Call(self, node: ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id in self.sessions and func.attr in SESSION_METHODS
        ):
            self.methods.add(func.attr)
        target = _reference(func, self.bindings)
        if target.startswith("app.models.") and target.removeprefix("app.models.") in self.model_names:
            self.models.add(target.removeprefix("app.models."))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # no_autoflush is normally a context manager property, not a call.
        if node.attr == "no_autoflush" and isinstance(node.value, ast.Name) and node.value.id in self.sessions:
            self.methods.add(node.attr)
        self.generic_visit(node)


def _scan():
    model_names = {
        name for name, value in vars(models).items()
        if isinstance(value, type) and hasattr(value, "__tablename__")
    }
    modules: set[str] = set()
    database_uses: dict[str, tuple[set[str], set[str]]] = {}
    upward_imports: set[tuple[str, str]] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name == "__init__.py" or "__pycache__" in path.parts:
            continue
        module = path.relative_to(APP_DIR).with_suffix("").as_posix()
        modules.add(module)
        # A BOM must not make a module invisible to the boundary guard.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        bindings: dict[str, str] = {}
        targets: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = _import_target(node, module)
                targets.add(target)
                for alias in node.names:
                    if alias.name == "*" and target == "app.models":
                        bindings.update({name: f"app.models.{name}" for name in model_names})
                    else:
                        imported = f"{target}.{alias.name}"
                        bindings[alias.asname or alias.name] = imported
                        targets.add(imported)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    targets.add(alias.name)
                    bindings[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        if _role(module) in {"ui", "workflow"}:
            uses = _DatabaseUses(bindings, model_names)
            uses.visit(tree)
            if uses.methods or uses.models:
                database_uses[module] = (uses.methods, uses.models)
        elif _role(module) == "service":
            upward_imports.update(
                (module, target.removeprefix("app.").replace(".", "/"))
                for target in targets
                if target.startswith("app.")
                and ROLE_BY_DIRECTORY.get(target.removeprefix("app.").split(".", 1)[0]) == "workflow"
            )
    return modules, database_uses, upward_imports


@pytest.fixture(scope="module")
def module_scan():
    # Both adapter rules share one snapshot and one pass over the application.
    return _scan()


@pytest.fixture(scope="module")
def scan(module_scan):
    modules, database_uses, upward_imports = module_scan
    return modules, {
        module: uses for module, uses in database_uses.items() if _role(module) == "ui"
    }, upward_imports


@pytest.fixture(scope="module")
def workflow_scan(module_scan):
    _, database_uses, _ = module_scan
    return {
        module: (methods - BOUNDARY_METHODS, model_names)
        for module, (methods, model_names) in database_uses.items()
        if _role(module) == "workflow" and (methods - BOUNDARY_METHODS or model_names)
    }


def test_every_module_has_a_role(scan):
    modules, _, _ = scan
    missing = sorted(module for module in modules if _role(module) is None)
    assert not missing, "Modules without roles:\n" + "\n".join(missing)


def test_ui_modules_do_not_touch_the_database(scan):
    _, database_uses, _ = scan
    violations = [
        f"{module}: session methods={sorted(methods)}; models={sorted(model_names)}"
        for module, (methods, model_names) in sorted(database_uses.items())
        if module not in ALLOWED
    ]
    assert not violations, "Unexpected UI database access:\n" + "\n".join(violations)


def test_the_allowed_list_has_no_stale_entries(scan):
    _, database_uses, _ = scan
    # Removing a router's last database use must also remove its exception.
    stale = sorted(module for module in ALLOWED if module not in database_uses)
    assert not stale, "Stale ALLOWED entries:\n" + "\n".join(stale)


def test_stale_entry_guard_rejects_an_exception_added_to_the_empty_list(scan, monkeypatch):
    assert ALLOWED == {}
    monkeypatch.setitem(ALLOWED, "routers/auth", "stale-entry probe")
    with pytest.raises(AssertionError, match=r"Stale ALLOWED entries:\s+routers/auth"):
        test_the_allowed_list_has_no_stale_entries(scan)


def test_a_service_never_imports_a_workflow(scan):
    _, _, upward_imports = scan
    violations = [f"{module} imports {target}" for module, target in sorted(upward_imports)]
    assert not violations, "Service imports workflow:\n" + "\n".join(violations)


def test_workflow_modules_do_not_access_data_or_construct_models(workflow_scan):
    violations = [
        f"{module}: session methods={sorted(methods)}; models={sorted(model_names)}"
        for module, (methods, model_names) in sorted(workflow_scan.items())
        if module not in WORKFLOW_ALLOWED
    ]
    assert not violations, "Unexpected workflow database access:\n" + "\n".join(violations)


def test_workflow_allowed_list_matches_observed_violations(workflow_scan):
    # The progress board must name every remaining violation, and removing the
    # last data access must remove that workflow's exception in the same wave.
    stale = sorted(set(WORKFLOW_ALLOWED) - set(workflow_scan))
    missing = sorted(set(workflow_scan) - set(WORKFLOW_ALLOWED))
    assert not (stale or missing), (
        "WORKFLOW_ALLOWED does not match observed violations:\n"
        f"stale entries={stale}\nmissing entries={missing}"
    )


def test_workflow_transaction_boundary_methods_are_allowed(module_scan, workflow_scan):
    _, database_uses, _ = module_scan
    methods, model_names = database_uses["workflows/ledger_entry_workflow"]
    assert "commit" in methods
    assert not (methods - BOUNDARY_METHODS or model_names)
    assert "workflows/ledger_entry_workflow" not in workflow_scan
    methods, model_names = database_uses["workflows/capsule_workflow"]
    assert "flush" in methods
    assert not (methods - BOUNDARY_METHODS or model_names)
    assert "workflows/capsule_workflow" not in workflow_scan


@pytest.fixture(scope="module")
def http_exception_counts():
    counts: dict[str, int] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        module = path.relative_to(APP_DIR).with_suffix("").as_posix()
        if _role(module) not in {"service", "workflow", "domain"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = _import_target(node, module)
                for alias in node.names:
                    bindings[alias.asname or alias.name] = f"{target}.{alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bindings[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
        count = sum(
            isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
            and _reference(node.exc.func, bindings) in {
                "fastapi.HTTPException", "fastapi.exceptions.HTTPException",
                "starlette.exceptions.HTTPException",
            }
            for node in ast.walk(tree)
        )
        if count:
            counts[module] = count
    return counts


def test_modules_below_http_do_not_raise_http_exception(http_exception_counts):
    violations = [
        f"{module}: raises={count}, allowed={HTTP_EXCEPTION_ALLOWED.get(module, 0)}"
        for module, count in sorted(http_exception_counts.items())
        if count > HTTP_EXCEPTION_ALLOWED.get(module, 0)
    ]
    assert not violations, "Unexpected HTTPException raises below HTTP:\n" + "\n".join(violations)


def test_http_exception_allowed_counts_have_no_stale_entries(http_exception_counts):
    # Each removed raise must shrink the exception in the same change, even
    # when that module still has other HTTPException raises left to convert.
    stale = [
        f"{module}: raises={http_exception_counts.get(module, 0)}, allowed={allowed}"
        for module, allowed in sorted(HTTP_EXCEPTION_ALLOWED.items())
        if module not in http_exception_counts or http_exception_counts[module] < allowed
    ]
    assert not stale, "Stale HTTP_EXCEPTION_ALLOWED counts:\n" + "\n".join(stale)


def test_http_stale_entry_guard_rejects_an_exception_added_to_the_empty_list(
    http_exception_counts, monkeypatch,
):
    assert HTTP_EXCEPTION_ALLOWED == {}
    monkeypatch.setitem(HTTP_EXCEPTION_ALLOWED, "services/ai_policy_service", 1)
    with pytest.raises(
        AssertionError,
        match=r"Stale HTTP_EXCEPTION_ALLOWED counts:\s+services/ai_policy_service: raises=0, allowed=1",
    ):
        test_http_exception_allowed_counts_have_no_stale_entries(http_exception_counts)


def test_domain_imports_only_standard_library_or_domain():
    violations: list[str] = []
    for path in sorted((APP_DIR / "domain").rglob("*.py")):
        module = path.relative_to(APP_DIR).with_suffix("").as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                target = _import_target(node, module)
                targets = [f"{target}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            for target in targets:
                if (
                    target.split(".", 1)[0] not in sys.stdlib_module_names
                    and target != "app.domain" and not target.startswith("app.domain.")
                ):
                    violations.append(f"{module}:{node.lineno} imports {target}")
    assert not violations, "Domain imports framework or outer application code:\n" + "\n".join(violations)
