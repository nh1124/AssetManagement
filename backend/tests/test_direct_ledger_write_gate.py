from __future__ import annotations

from app.services.ledger_valuation import calculate_account_valued_balance

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.services import ai_policy_service
from backend.app.services.ai_policy_service import set_operation_mode
from backend.app.utils.jwt import create_access_token
from test_journal_legs_api import _client

MCP_HEADERS = {"X-MCP-Client-Id": "direct-ledger-test"}


@pytest.fixture
def http_ledger():
    # TestClient crosses threads, so all sessions need the same in-memory database.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = sessions()
    client = _client(db)
    cash = models.Account(client_id=client.id, name="Cash", account_type="asset")
    food = models.Account(client_id=client.id, name="Food", account_type="expense")
    db.add_all([cash, food])
    db.commit()
    payload = {
        "date": "2026-10-11",
        "description": "Direct ledger lunch",
        "amount": 1200,
        "currency": "JPY",
        "from_account_id": cash.id,
        "to_account_id": food.id,
    }

    def override_db():
        with sessions() as session:
            yield session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    # Leaving lifespan inactive avoids production migrations and background posting.
    http = TestClient(app, headers={
        "Authorization": f"Bearer {create_access_token(str(client.id), client.username)}",
    })
    try:
        yield http, db, payload
    finally:
        http.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        db.close()
        engine.dispose()


def _snapshot(db):
    # Counts alone miss edits to journal legs, balances, or existing proposals.
    # The AI audit is left out: it records the refused attempt (WP34), which
    # test_wp34_ai_operation_audit checks; nothing else may change.
    state = {
        table.name: [dict(row) for row in db.execute(
            select(table).order_by(*table.primary_key.columns),
        ).mappings()]
        for table in Base.metadata.tables.values()
        if table.name != "ai_audit_logs"
    }
    return json.dumps(state, sort_keys=True, default=str).encode("utf-8")


def _open_gate(db, operation="transactions.create", mode="allow"):
    set_operation_mode(db, 1, operation, mode, None)


def _assert_posted(db, response, payload):
    assert response.status_code == 200, response.text
    db.expire_all()
    transaction = db.query(models.Transaction).one()
    assert response.json()["id"] == transaction.id
    assert transaction.amount == payload["amount"]
    assert sorted((leg.account_id, leg.debit, leg.credit) for leg in transaction.journal_entries) == sorted([
        (payload["from_account_id"], 0, payload["amount"]),
        (payload["to_account_id"], payload["amount"], 0),
    ])
    assert calculate_account_valued_balance(db, db.get(models.Account, payload["from_account_id"])) == -payload["amount"]
    assert calculate_account_valued_balance(db, db.get(models.Account, payload["to_account_id"])) == payload["amount"]
    assert db.query(models.TransactionProposal).count() == 0


def _assert_refused(response, reason):
    # The gateway refuses before the endpoint runs, naming why (WP36).
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert (detail["error"], detail["reason"]) == ("ai_operation_refused", reason)


@pytest.mark.parametrize("headers", [
    {},
    {"X-MCP-Client-Id": ""},
    {"X-MCP-Username": "agent", "X-MCP-Backend-Client-Id": "1", "X-MCP-Tool-Name": "transactions_create"},
], ids=["human", "empty-mcp-id", "other-mcp-headers-only"])
def test_human_create_posts_without_policy_evaluation(http_ledger, monkeypatch, headers):
    http, db, payload = http_ledger
    assert db.query(models.AiOperationPolicy).count() == 0

    def fail_policy_lookup(*args, **kwargs):
        pytest.fail("A human write must not query AI policy")

    monkeypatch.setattr(ai_policy_service, "operation_mode", fail_policy_lookup)

    _assert_posted(db, http.post("/transactions/", json=payload, headers=headers), payload)


def test_mcp_create_refused_then_posts_same_payload_when_policy_opens(http_ledger):
    http, db, payload = http_ledger
    assert db.query(models.AiOperationPolicy).count() == 0
    before = _snapshot(db)

    refused = http.post("/transactions/", json=payload, headers=MCP_HEADERS)

    # Recording a transaction defaults to needing a change request.
    _assert_refused(refused, "operation_needs_approval")
    assert _snapshot(db) == before
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0
    assert db.query(models.TransactionProposal).count() == 0

    _open_gate(db)
    allowed = http.post("/transactions/", json=payload, headers=MCP_HEADERS)

    _assert_posted(db, allowed, payload)


def test_the_permission_row_on_the_screen_opens_the_gate(http_ledger):
    # What 自動化 › AI sends when the owner sets 取引を記録する to 許可 (WP36).
    http, db, payload = http_ledger
    listed = http.get("/ai/operations").json()
    row = next(entry for section in listed["sections"] for entry in section["operations"] if entry["key"] == "transactions.create")
    assert (row["mode"], row["saved"], row["modes"]) == ("approval", False, ["allow", "approval", "deny"])
    _assert_refused(http.post("/transactions/", json=payload, headers=MCP_HEADERS), "operation_needs_approval")

    stale = http.put("/ai/operations/transactions.create", json={"mode": "allow", "expected_mode": "deny"})
    assert stale.status_code == 409, stale.text
    saved = http.put("/ai/operations/transactions.create", json={"mode": "allow", "expected_mode": "approval"})

    assert saved.status_code == 200, saved.text
    assert (saved.json()["mode"], saved.json()["saved"]) == ("allow", True)
    _assert_posted(db, http.post("/transactions/", json=payload, headers=MCP_HEADERS), payload)


@pytest.mark.parametrize("setting, reason", [
    ({"mode": "deny"}, "operation_denied"),
    ({"mode": "approval"}, "operation_needs_approval"),
    ({"operation": "transactions.update"}, "operation_needs_approval"),
    ({"client_id": 2}, "operation_needs_approval"),
], ids=["deny", "approval", "another-operation", "other-client"])
def test_mcp_create_needs_its_own_permission_at_allow(http_ledger, setting, reason):
    http, db, payload = http_ledger
    if "client_id" in setting:
        db.add(models.Client(id=2, name="Other test client", general_settings={}))
        db.commit()
        db.add(models.AiOperationPolicy(client_id=2, operation="transactions.create", mode="allow"))
        db.commit()
    else:
        _open_gate(db, **setting)
    before = _snapshot(db)

    _assert_refused(http.post("/transactions/", json=payload, headers=MCP_HEADERS), reason)

    assert _snapshot(db) == before


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_mcp_update_delete_refused_then_allowed_with_ledger_policy(http_ledger, operation):
    http, db, payload = http_ledger
    created = http.post("/transactions/", json=payload)
    _assert_posted(db, created, payload)
    transaction_id = created.json()["id"]
    before = _snapshot(db)
    path = f"/transactions/{transaction_id}"
    patch = {"amount": 1500, "description": "Updated lunch"}

    if operation == "update":
        refused = http.put(path, json=patch, headers=MCP_HEADERS)
    else:
        refused = http.delete(path, headers=MCP_HEADERS)

    # Each ledger operation has its own permission; allowing the create does not open these.
    _assert_refused(refused, "operation_denied")
    assert _snapshot(db) == before
    _open_gate(db)
    assert (http.put(path, json=patch, headers=MCP_HEADERS) if operation == "update"
            else http.delete(path, headers=MCP_HEADERS)).status_code == 403

    _open_gate(db, f"transactions.{operation}")
    if operation == "update":
        allowed = http.put(path, json=patch, headers=MCP_HEADERS)
        _assert_posted(db, allowed, {**payload, **patch})
        assert allowed.json()["description"] == patch["description"]
    else:
        allowed = http.delete(path, headers=MCP_HEADERS)
        assert allowed.status_code == 200
        assert allowed.json() == {"message": "Transaction deleted"}
        db.expire_all()
        assert db.query(models.Transaction).count() == 0
        assert db.query(models.JournalEntry).count() == 0
        assert calculate_account_valued_balance(db, db.get(models.Account, payload["from_account_id"])) == 0
        assert calculate_account_valued_balance(db, db.get(models.Account, payload["to_account_id"])) == 0
    assert db.query(models.TransactionProposal).count() == 0


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_human_update_delete_skip_policy_evaluation(http_ledger, monkeypatch, operation):
    http, db, payload = http_ledger
    created = http.post("/transactions/", json=payload)
    _assert_posted(db, created, payload)
    path = f"/transactions/{created.json()['id']}"
    assert db.query(models.AiOperationPolicy).count() == 0

    def fail_policy_lookup(*args, **kwargs):
        pytest.fail("A human write must not query AI policy")

    monkeypatch.setattr(ai_policy_service, "operation_mode", fail_policy_lookup)

    if operation == "update":
        response = http.put(path, json={"amount": 1500})
        _assert_posted(db, response, {**payload, "amount": 1500})
    else:
        response = http.delete(path)
        assert response.status_code == 200
        assert db.query(models.Transaction).count() == 0
        assert db.query(models.JournalEntry).count() == 0
        assert db.query(models.TransactionProposal).count() == 0


@pytest.mark.parametrize("path, body", [
    ("/transaction-batches/", {"transactions": []}),
    ("/capsules/1/drawdown", {"amount": 1, "from_account_id": 1, "to_account_id": 2, "kind": "as_intended", "date": "2026-10-11", "description": "x"}),
    ("/capsules/1/account-claim", {"account_id": 1, "target_amount": 1}),
    ("/capsules/1/contribute", {"amount": 1, "from_account_id": 1}),
], ids=["batch", "drawdown", "account-claim", "contribute"])
def test_every_mcp_ledger_write_is_denied_by_default(http_ledger, path, body):
    # The other operations that post journal legs had no approval path: denied until allowed (WP36).
    http, db, _ = http_ledger
    before = _snapshot(db)
    _assert_refused(http.post(path, json=body, headers=MCP_HEADERS), "operation_denied")
    assert _snapshot(db) == before
