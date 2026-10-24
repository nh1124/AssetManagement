"""WP36: one list of AI operations drives the gateway, the audit and the screen (owner 2026-10-24, C8-C10).

The list has to keep up with the MCP server: every backend call an MCP tool makes
must be one operation (or plumbing), every tool must be listed, and every listed
route must exist in the backend. A request the list does not know is refused.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domain import ai_operations as catalog
from app.main import app
from app.workflows.ai_change_request_workflow import SUPPORTED_OPERATIONS

ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = ROOT / "mcp" / "src"
CONTRACTS = json.loads((ROOT / "mcp" / "contracts" / "write-tools.json").read_text(encoding="utf-8"))
# POSTs that only read or check; they are not in the write contract.
READ_POSTS = {"/ai/change-requests/preview", "/data/import/validate", "/plan/reflection/preview"}
_CALL = re.compile(r'api\.(get|post|put|patch|delete)(?:<[^>]*>)?\(\s*(`[^`]*`|"[^"]*")')


def _concrete(path: str) -> str:
    """A path template as a request would carry it: placeholders become an id, the query goes."""
    return re.sub(r"\$\{[^}]*\}|\{[^}]+\}", "7", path).split("?")[0]


def _mcp_calls() -> list[tuple[str, str]]:
    calls = set()
    for source in MCP_SRC.rglob("*.ts"):
        for match in _CALL.finditer(source.read_text(encoding="utf-8")):
            calls.add((match.group(1).upper(), match.group(2)[1:-1]))
    return sorted(calls)


def _best(method: str, path: str):
    candidates = [route for route in catalog._ROUTES
                  if route.method == method and route.pattern.match(catalog._normalize(path))]
    if not candidates:
        return []
    top = max((not route.prefix, route.literals) for route in candidates)
    return [route for route in candidates if (not route.prefix, route.literals) == top]


def test_every_write_the_mcp_server_makes_is_exactly_one_operation():
    for contract in CONTRACTS:
        method, path = contract["method"].upper(), _concrete(contract["path"])
        best = _best(method, path)
        assert len({route.operation for route in best}) == 1, f"{method} {contract['path']}: {best}"
        operation = best[0].operation
        assert operation is not None and operation.kind == "write", f"{method} {contract['path']}"
        assert contract["tool"] in operation.tools, f"{contract['tool']} is not listed on {operation.key}"


def test_every_read_the_mcp_server_makes_is_exactly_one_operation():
    contract_writes = {(contract["method"].upper(), contract["path"].strip("/").split("/")[0]) for contract in CONTRACTS}
    for method, raw in _mcp_calls():
        path = _concrete(raw)
        if method != "GET" and catalog._normalize(path) not in READ_POSTS:
            # A write: the contract test above covers it (dynamic spellings such as /products/${...}).
            assert (method, path.strip("/").split("/")[0]) in contract_writes, f"{method} {raw} is neither a read nor a contract write"
            continue
        best = _best(method, path)
        assert len({route.operation for route in best}) == 1, f"{method} {raw}: {best}"
        operation = best[0].operation
        assert operation is None or operation.kind == "read", f"{method} {raw} is a read but maps to {operation.key}"


def test_every_mcp_tool_is_on_the_list():
    registered = set()
    for source in MCP_SRC.rglob("*.ts"):
        registered |= set(re.findall(r'(?:registerTool\(\s*|register\(server,\s*)"([a-z_]+)"', source.read_text(encoding="utf-8")))
    listed = {tool for operation in catalog.OPERATIONS for tool in operation.tools} | set(catalog.LOCAL_TOOLS)
    assert registered == listed, {"missing from the list": sorted(registered - listed), "not an MCP tool": sorted(listed - registered)}


def _app_routes():
    for route in app.routes:
        # FastAPI keeps included routers as lazy branches (see test_read_endpoints_do_not_write).
        yield from (route.effective_route_contexts() if hasattr(route, "effective_route_contexts") else [route])


def test_every_listed_route_exists_in_the_backend():
    routes = {(method, "/" + re.sub(r"\{[^}]+\}", "{id}", route.path).strip("/"))
              for route in _app_routes() if getattr(route, "methods", None) for method in route.methods}
    for operation in catalog.OPERATIONS:
        for spec in operation.routes:
            method, path = spec.split(" ", 1)
            if path.endswith("/**"):
                prefix = path.removesuffix("/**")
                assert any(m == method and (p == prefix or p.startswith(prefix + "/")) for m, p in routes), spec
            else:
                assert (method, "/" + path.strip("/")) in routes, f"{operation.key}: {spec}"
    for spec in catalog.PLUMBING:
        assert tuple(spec.split(" ", 1)) in routes, spec


def test_operations_are_unique_and_well_formed():
    assert len(catalog.BY_KEY) == len(catalog.OPERATIONS)
    sections = {section.key for section in catalog.SECTIONS}
    for operation in catalog.OPERATIONS:
        assert operation.section in sections and operation.ja and operation.en and operation.tools, operation.key
        assert operation.default in operation.modes, operation.key
        if operation.ledger:
            assert operation.kind == "write" and operation.default in {"approval", "deny"}, operation.key
    assert set(SUPPORTED_OPERATIONS.values()) == {operation.key for operation in catalog.OPERATIONS if operation.approval}


@pytest.mark.parametrize("method, path, key", [
    ("GET", "/analysis/reconcile/40", "accounts.read"),
    ("GET", "/analysis/summary", "analysis.read"),
    ("POST", "/analysis/reconcile/40/adjust", "accounts.reconcile_adjust"),
    ("PUT", "/capsules/rules/3", "capsule_rules.update"),
    ("PUT", "/capsules/3/funding-sources", "capsules.funding_sources"),
    ("POST", "/ai/change-requests/preview", "change_requests.read"),
    ("POST", "/ai/change-requests/5/refresh-preview", "change_requests.create"),
    ("POST", "/products/", "products.create"),
    ("DELETE", "/exchange-rates/tracked/USD", "fx_tracked.delete"),
])
def test_the_most_specific_route_wins(method, path, key):
    known, operation = catalog.match(method, path)
    assert known and operation.key == key


def test_unknown_and_plumbing_requests():
    assert catalog.match("GET", "/ai/execution-settings") == (True, None)
    assert catalog.match("POST", "/ai/evaluate") == (False, None)
    assert catalog.match("DELETE", "/accounts/") == (False, None)


# ─── the migration keeps what took effect ───────────────────────────────────

def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261024_0094_ai_operation_permissions.py"
    spec = importlib.util.spec_from_file_location("wp36_permissions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _old_database():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table("clients", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("ai_operation_policies", metadata,
             sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=False),
             sa.Column("ai_client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=True, index=True),
             sa.Column("resource", sa.String, nullable=False), sa.Column("action", sa.String, nullable=False),
             sa.Column("risk", sa.String, nullable=False), sa.Column("mode", sa.String, nullable=False),
             sa.Column("threshold_amount_minor", sa.BigInteger), sa.Column("threshold_count", sa.Integer),
             sa.Column("require_mfa", sa.Boolean, nullable=False, server_default="false"),
             sa.Column("created_at", sa.DateTime, nullable=False), sa.Column("updated_at", sa.DateTime, nullable=False),
             sa.UniqueConstraint("client_id", "ai_client_id", "resource", "action", "risk", name="_client_ai_policy_uc"))
    sa.Table("ai_change_requests", metadata,
             sa.Column("id", sa.Integer, primary_key=True), sa.Column("client_id", sa.Integer, nullable=False),
             sa.Column("ai_client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=True, index=True),
             sa.Column("requires_mfa", sa.Boolean, nullable=False, server_default="false"))
    sa.Table("ai_audit_logs", metadata,
             sa.Column("id", sa.Integer, primary_key=True), sa.Column("client_id", sa.Integer, nullable=False),
             sa.Column("ai_client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=True, index=True))
    metadata.create_all(engine)
    now = "2026-10-24 00:00:00"
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO clients (id) VALUES (1), (2), (3)"))
        rows = [
            (2, "transactions", "create", "medium", "allow_execute", False),
            (3, "transactions", "create", "high", "allow_execute", False),
            (3, "transactions", "create", "medium", "require_approval", False),
            (3, "auto_transactions", "update", "medium", "deny", False),
            (3, "ai_context", "read", "low", "deny", False),
            (3, "exchange_rates", "update", "low", "deny", False),
            (1, "transactions", "create", "medium", "allow_execute", True),
        ]
        for client_id, resource, action, risk, mode, mfa in rows:
            connection.execute(sa.text(
                "INSERT INTO ai_operation_policies (client_id, resource, action, risk, mode, require_mfa, created_at, updated_at) "
                "VALUES (:c, :r, :a, :k, :m, :f, :n, :n)"), {"c": client_id, "r": resource, "a": action, "k": risk, "m": mode, "f": mfa, "n": now})
        connection.execute(sa.text("INSERT INTO ai_change_requests (id, client_id, requires_mfa) VALUES (1, 2, 1)"))
        connection.execute(sa.text("INSERT INTO ai_audit_logs (id, client_id) VALUES (1, 2)"))
    return engine


def _run(engine, direction):
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_migration(), direction)()


def _permissions(engine):
    with engine.connect() as connection:
        return {(row.client_id, row.operation): row.mode for row in connection.execute(
            sa.text("SELECT client_id, operation, mode FROM ai_operation_policies"))}


def test_the_migration_carries_over_what_took_effect():
    engine = _old_database()
    _run(engine, "upgrade")
    saved = _permissions(engine)
    ledger = _migration().LEDGER_OPERATIONS
    # Client 2 let the AI write the ledger directly: every ledger operation is allowed.
    assert {key: mode for (client, key), mode in saved.items() if client == 2} == dict.fromkeys(ledger, "allow")
    # Client 3: the medium rule is what the gate read; the AI context read stays denied.
    assert saved[(3, "transactions.create")] == "approval"
    assert all(saved[(3, key)] == "deny" for key in ledger if key != "transactions.create")
    assert saved[(3, "auto_transactions.update")] == "deny" and saved[(3, "ai_context.read")] == "deny"
    assert not any(key.startswith("exchange_rates") for _, key in saved)
    # Client 1's rule needed an MFA no direct write could show: it never opened the gate.
    assert saved[(1, "transactions.create")] == "approval" and saved[(1, "transactions.update")] == "deny"
    with engine.connect() as connection:
        columns = {table: {column["name"] for column in sa.inspect(connection).get_columns(table)}
                   for table in ("ai_operation_policies", "ai_change_requests", "ai_audit_logs")}
    assert columns["ai_operation_policies"] == {"id", "client_id", "operation", "mode", "created_at", "updated_at"}
    assert "ai_client_id" not in columns["ai_change_requests"] | columns["ai_audit_logs"]
    assert "requires_mfa" not in columns["ai_change_requests"]

    _run(engine, "downgrade")
    with engine.connect() as connection:
        restored = connection.execute(sa.text(
            "SELECT client_id, resource, action, risk, mode FROM ai_operation_policies")).fetchall()
    assert [tuple(row) for row in restored] == [(2, "transactions", "create", "medium", "allow_execute")]
