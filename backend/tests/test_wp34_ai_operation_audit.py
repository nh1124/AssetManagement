"""WP34: every MCP request is an audited AI operation, bound to its token and scoped.

The owner (2026-10-24): log every AI operation that comes through MCP -- reads,
direct writes, approvals queued -- with what let it through; keep the AI from
changing its own permissions or approving; and rebuild the day's operations
from the backend's log.
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.maintenance import restore_ai_audit
from backend.app.routers import auth
from backend.app.services import ai_policy_service
from backend.app.services.ai_policy_service import describe_mcp_request, replace_client_policies
from backend.app.utils.jwt import create_access_token, create_typed_token, decode_token
from backend.app.utils.observability import install_db_audit
from test_journal_legs_api import _client
from test_mcp_token_exchange import _client as _mfa_client, _connect, _mcp_token, _session

MCP_CLIENT = "mcp_wp34"
# The connection the gateway fixture opens: an MCP token names one (WP35).
MCP_CONNECTION = 77
TOOL = {"X-MCP-Tool-Name": "transactions_create"}


def _mcp_bearer(client) -> dict:
    token = create_typed_token(
        user_id=str(client.id), username=client.username, token_type="access",
        extra_claims={"chn": "mcp", "mcp_client_id": MCP_CLIENT, "cid": MCP_CONNECTION},
    )
    return {"Authorization": f"Bearer {token}"}


def _ui_bearer(client) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(client.id), client.username)}"}


@pytest.fixture
def gateway():
    # TestClient crosses threads, so every session must share one in-memory database.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # The audit collects the rows a request committed from the session hooks.
    install_db_audit(sessions)
    db = sessions()
    client = _client(db)
    _connect(db, client.id, oauth_client_id=MCP_CLIENT, connection_id=MCP_CONNECTION)
    cash = models.Account(client_id=client.id, name="Cash", account_type="asset")
    food = models.Account(client_id=client.id, name="Food", account_type="expense")
    db.add_all([cash, food])
    db.commit()
    lunch = {
        "date": "2026-10-11", "description": "Lunch", "amount": 1200, "currency": "JPY",
        "from_account_id": cash.id, "to_account_id": food.id,
    }

    def override_db():
        with sessions() as session:
            yield session

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    http = TestClient(app)
    try:
        yield http, db, client, lunch
    finally:
        http.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        db.close()
        engine.dispose()


def _rows(db) -> list[models.AiAuditLog]:
    db.expire_all()
    return db.query(models.AiAuditLog).order_by(models.AiAuditLog.id).all()


def _open_ledger_gate(db, client) -> int:
    policies = replace_client_policies(db, client.id, [{
        "resource": "transactions", "action": "create", "risk": "medium",
        "mode": "allow_execute", "require_mfa": False,
    }])
    return policies[0].id


# ─── the token decides the channel ──────────────────────────────────────────

def test_exchanged_token_is_bound_to_the_mcp_channel():
    db = _session()
    try:
        client = _mfa_client(db, 1, "alice")
        token = _mcp_token(username="alice", backend_client_id=client.id, cid=_connect(db, client.id))
        result = auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)
        payload = decode_token(result["access_token"])
        assert payload["chn"] == "mcp"
        assert payload["mcp_client_id"] == "mcp_test_client"
        assert payload["sub"] == str(client.id) and payload["type"] == "access"
    finally:
        db.close()


def test_extra_claims_cannot_replace_the_subject():
    token = create_typed_token("7", "u", "access", extra_claims={"sub": "1", "type": "refresh", "chn": "mcp"})
    payload = decode_token(token)
    assert payload["sub"] == "7" and payload["type"] == "access" and payload["chn"] == "mcp"


def test_an_mcp_token_without_the_header_is_still_gated_and_audited(gateway):
    http, db, client, lunch = gateway
    response = http.post("/transactions/", json=lunch, headers=_mcp_bearer(client))
    assert response.status_code == 403
    assert db.query(models.Transaction).count() == 0
    [row] = _rows(db)
    assert (row.authorization, row.decision, row.http_status) == ("refused_policy", "denied", 403)
    assert row.mcp_client_id == MCP_CLIENT and row.source == "mcp_http"
    assert "Direct MCP ledger write refused" in json.dumps(row.result_summary)


def test_a_persons_requests_are_not_ai_operations(gateway):
    http, db, client, lunch = gateway
    assert http.post("/transactions/", json=lunch, headers=_ui_bearer(client)).status_code == 200
    assert http.get("/accounts/", headers=_ui_bearer(client)).status_code == 200
    assert _rows(db) == []


# ─── every operation gets one row, with what let it through ─────────────────

def test_a_direct_ledger_write_names_the_rule_that_allowed_it(gateway):
    http, db, client, lunch = gateway
    policy_id = _open_ledger_gate(db, client)
    response = http.post("/transactions/", json=lunch, headers={**_mcp_bearer(client), **TOOL, "X-Request-ID": "mcp-call-0001"})
    assert response.status_code == 200
    [row] = _rows(db)
    assert (row.resource, row.action, row.decision, row.authorization) == ("transactions", "create", "applied", "direct_policy")
    assert row.result_summary["authorization"]["policy"] == {
        "id": policy_id, "resource": "transactions", "action": "create", "risk": "medium",
        "mode": "allow_execute", "require_mfa": False,
    }
    assert row.result_summary["authorization"]["mcp_write_mode"] == "direct_write"
    assert row.tool_name == "transactions_create"
    assert row.correlation_id == "mcp-call-0001" and row.request_id and row.http_status == 200
    assert row.request_summary["method"] == "POST" and row.request_summary["path"] == "/transactions/"
    assert row.request_summary["body"]["amount"] == 1200
    assert row.diff_summary["tables"]["transactions"] == 1
    assert row.diff_summary["tables"]["journal_entries"] == 2
    created = next(change for change in row.diff_summary["changes"] if change["table"] == "transactions")
    assert created["op"] == "insert" and created["values"]["description"] == "Lunch"


def test_a_write_off_the_ledger_is_allowed_by_the_write_mode(gateway):
    http, db, client, _ = gateway
    response = http.post("/accounts/", json={"name": "Wallet", "account_type": "asset"}, headers=_mcp_bearer(client))
    assert response.status_code == 200
    [row] = _rows(db)
    assert (row.resource, row.action, row.authorization, row.decision) == ("accounts", "create", "direct_mode", "applied")
    assert "policy" not in row.result_summary["authorization"]
    assert row.diff_summary["tables"] == {"accounts": 1}


def test_reads_are_audited(gateway):
    http, db, client, _ = gateway
    assert http.get("/accounts/", headers=_mcp_bearer(client)).status_code == 200
    [row] = _rows(db)
    assert (row.resource, row.action, row.risk, row.authorization, row.decision) == ("accounts", "read", "low", "read", "allowed")
    assert row.diff_summary == {}


def test_the_write_mode_check_of_the_mcp_server_is_not_an_operation(gateway):
    http, db, client, _ = gateway
    assert http.get("/ai/execution-settings", headers=_mcp_bearer(client)).status_code == 200
    assert _rows(db) == []


def test_an_endpoint_that_audits_itself_gets_its_row_completed_not_doubled(gateway):
    http, db, client, _ = gateway
    response = http.post(
        "/ai/evaluate", json={"resource": "transactions", "action": "create", "risk": "medium"},
        headers={**_mcp_bearer(client), "X-Request-ID": "mcp-call-0002"},
    )
    assert response.status_code == 200
    [row] = _rows(db)
    assert row.resource == "transactions"  # the endpoint's own description is kept
    assert (row.authorization, row.http_status, row.correlation_id) == ("read", 200, "mcp-call-0002")
    assert row.request_summary["http"]["path"] == "/ai/evaluate"


# ─── what the AI may never do ───────────────────────────────────────────────

@pytest.mark.parametrize("method, path, body, reason", [
    ("put", "/ai/policies", [{"resource": "transactions", "action": "create", "risk": "medium", "mode": "allow_execute"}], "ai_permissions"),
    ("put", "/ai/execution-settings", {"mcp_write_mode": "direct_write"}, "ai_permissions"),
    ("post", "/ai/change-requests/1/approve", {}, "human_approval"),
    ("post", "/ai/change-requests/1/reject", {}, "human_approval"),
    ("post", "/transactions/proposals/1/approve", {}, "human_approval"),
    ("post", "/transactions/proposals/1/reject", {}, "human_approval"),
    ("post", "/auth/password-change", {"current_password": "x", "new_password": "y"}, "account"),
    ("patch", "/auth/me", {"name": "x"}, "account"),
])
def test_the_ai_cannot_raise_its_own_permissions_act_on_the_account_or_approve(gateway, method, path, body, reason):
    http, db, client, _ = gateway
    response = http.request(method.upper(), path, json=body, headers=_mcp_bearer(client))
    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == reason
    assert db.query(models.AiOperationPolicy).count() == 0
    [row] = _rows(db)
    assert (row.authorization, row.decision, row.http_status) == ("refused_scope", "denied", 403)
    assert row.result_summary["authorization"]["refusal"] == reason
    if path.startswith("/auth"):
        assert "body" not in row.request_summary  # credentials are never kept
    elif body:
        assert row.request_summary["body"]  # what the AI tried is on record


def test_a_person_still_changes_ai_permissions(gateway):
    http, db, client, _ = gateway
    rules = [{"resource": "transactions", "action": "create", "risk": "medium", "mode": "allow_execute"}]
    assert http.put("/ai/policies", json=rules, headers=_ui_bearer(client)).status_code == 200
    assert db.query(models.AiOperationPolicy).count() == 1


def test_the_ai_cannot_set_its_write_mode_through_the_general_settings(gateway):
    http, db, client, _ = gateway
    refused = http.put(f"/clients/{client.id}/settings", headers=_mcp_bearer(client),
                       json={"general_settings": {"ai_operation": {"mcp_write_mode": "direct_write"}}})
    assert refused.status_code == 403
    assert refused.json()["detail"]["reason"] == "ai_permissions"
    allowed = http.put(f"/clients/{client.id}/settings", headers=_mcp_bearer(client),
                       json={"general_settings": {"language": "en"}})
    assert allowed.status_code == 200
    first, second = _rows(db)
    assert (first.authorization, second.authorization) == ("refused_scope", "direct_mode")
    db.expire_all()
    assert "ai_operation" not in (db.get(models.Client, client.id).general_settings or {})


def test_change_request_mode_is_enforced_by_the_backend(gateway):
    http, db, client, lunch = gateway
    _open_ledger_gate(db, client)
    client.general_settings = {"ai_operation": {"mcp_write_mode": "change_request"}}
    db.commit()
    refused = http.post("/transactions/", json=lunch, headers=_mcp_bearer(client))
    assert refused.status_code == 403
    assert refused.json()["detail"]["reason"] == "change_request_mode"
    assert db.query(models.Transaction).count() == 0
    assert http.get("/accounts/", headers=_mcp_bearer(client)).status_code == 200
    refused_row, read_row = _rows(db)
    assert (refused_row.authorization, refused_row.decision) == ("refused_mode", "denied")
    assert read_row.authorization == "read"


# ─── describing a request ───────────────────────────────────────────────────

@pytest.mark.parametrize("method, path, expected", [
    ("GET", "/accounts/", ("accounts", "read", "low", None)),
    ("PUT", "/transactions/358", ("transactions", "update", "medium", 358)),
    ("DELETE", "/life-events/12", ("life_events", "delete", "high", 12)),
    ("POST", "/capsules/3/contribute", ("capsules", "contribute", "medium", 3)),
    ("POST", "/analysis/reconcile/40/adjust", ("analysis.reconcile", "adjust", "high", 40)),
    ("POST", "/ai/change-requests/5/apply", ("ai.change_requests", "apply", "medium", 5)),
    ("POST", "/transaction-batches/preview", ("transaction_batches", "preview", "low", None)),
    ("PUT", "/clients/2/settings", ("clients.settings", "update", "medium", 2)),
    ("POST", "/data/import/validate", ("data.import", "preview", "low", None)),
])
def test_describe_mcp_request(method, path, expected):
    assert describe_mcp_request(method, path) == expected


# ─── rebuilding from the backend's log ──────────────────────────────────────

def _log(event, request_id, **fields):
    base = {"ts": "2026-10-24T00:27:38.652+00:00", "event": event, "request_id": request_id,
            "correlation_id": f"mcp-{request_id}", "actor_client_id": 1, "channel": "mcp",
            "mcp_client_id": "mcp_80c3", "mcp_tool": "transactions_update"}
    return json.dumps({**base, **fields})


def test_the_days_operations_are_rebuilt_from_the_log_once(gateway):
    _, db, client, _ = gateway
    _open_ledger_gate(db, client)
    lines = [
        "uvicorn noise that is not json",
        _log("request.start", "r1", component="backend", method="PUT", path="/transactions/358", query=""),
        _log("request.end", "r1", component="backend", status=403, duration_ms=12.2),
        _log("request.start", "r2", component="backend", method="PUT", path="/transactions/358", query="",
             ts="2026-10-24T00:42:01.000+00:00"),
        _log("db.change", "r2", logger="app.audit", seq=1, table="transactions", op="update", pk=358,
             changes={"description": ["old", "new"]}),
        _log("db.change", "r2", logger="app.audit", seq=2, table="journal_entries", op="insert", pk=2033,
             values={"account_id": 103}),
        _log("request.end", "r2", component="backend", status=200, duration_ms=30.1),
        # Plumbing and someone else's request are not restored.
        _log("request.start", "r3", component="backend", method="GET", path="/ai/execution-settings", query=""),
        _log("request.end", "r3", component="backend", status=200),
        _log("request.start", "r4", component="backend", method="GET", path="/accounts/", query="", actor_client_id=99),
        _log("request.end", "r4", component="backend", status=200),
    ]
    tally = restore_ai_audit.restore(db, client.id, lines, apply=True)
    assert tally["written"] == 2
    refused, applied = _rows(db)
    assert (refused.authorization, refused.decision, refused.http_status) == ("refused_policy", "denied", 403)
    assert (applied.authorization, applied.decision) == ("direct_policy", "applied")
    assert applied.created_at == datetime(2026, 10, 24, 0, 42, 1)
    assert applied.request_summary["restored_from"] == "backend_log"
    assert applied.diff_summary["tables"] == {"transactions": 1, "journal_entries": 1}
    assert applied.tool_name == "transactions_update" and applied.correlation_id == "mcp-r2"
    again = restore_ai_audit.restore(db, client.id, lines, apply=True)
    assert again["already_audited"] == 2 and "written" not in again
    assert len(_rows(db)) == 2
