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
from backend.app.services.ai_policy_service import replace_client_policies
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
    state = {
        table.name: [dict(row) for row in db.execute(
            select(table).order_by(*table.primary_key.columns),
        ).mappings()]
        for table in Base.metadata.tables.values()
    }
    return json.dumps(state, sort_keys=True, default=str).encode("utf-8")


def _open_gate(db, risk="medium", **overrides):
    policy = {
        "resource": "transactions", "action": "create", "risk": risk,
        "mode": "allow_execute",
    }
    policy.update(overrides)
    replace_client_policies(db, 1, [policy])


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


def _assert_refused(response, risk):
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert "Direct MCP ledger write refused" in detail
    assert f"ai_operation_policies row for transactions / create / {risk}" in detail
    assert "allow_execute" in detail
    assert "change-request path" in detail


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

    monkeypatch.setattr(ai_policy_service, "_find_policy", fail_policy_lookup)

    _assert_posted(db, http.post("/transactions/", json=payload, headers=headers), payload)


def test_mcp_create_refused_then_posts_same_payload_when_policy_opens(http_ledger):
    http, db, payload = http_ledger
    assert db.query(models.AiOperationPolicy).count() == 0
    before = _snapshot(db)

    refused = http.post("/transactions/", json=payload, headers=MCP_HEADERS)

    _assert_refused(refused, "medium")
    assert _snapshot(db) == before
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0
    assert db.query(models.TransactionProposal).count() == 0

    _open_gate(db)
    allowed = http.post("/transactions/", json=payload, headers=MCP_HEADERS)

    _assert_posted(db, allowed, payload)
    print(f"No policy: {refused.status_code} {refused.json()}")
    print(f"Policy transactions/create/medium=allow_execute: {allowed.status_code} {allowed.json()}")


def test_rule_added_on_the_permission_screen_opens_the_gate(http_ledger):
    # What 自動化 › AI sends when the owner adds transactions / create / 中 as 実行を許可
    # with no rules saved yet (frontend policyRules.newPolicyPayload).
    http, db, payload = http_ledger
    assert http.get("/ai/policies").json() == []
    _assert_refused(http.post("/transactions/", json=payload, headers=MCP_HEADERS), "medium")

    saved = http.put("/ai/policies", json=[{
        "ai_client_id": None, "resource": "transactions", "action": "create", "risk": "medium",
        "mode": "allow_execute", "threshold_amount": None, "threshold_count": None, "require_mfa": False,
    }])

    assert saved.status_code == 200, saved.text
    assert [(row["resource"], row["action"], row["risk"], row["mode"]) for row in saved.json()] == [
        ("transactions", "create", "medium", "allow_execute"),
    ]
    _assert_posted(db, http.post("/transactions/", json=payload, headers=MCP_HEADERS), payload)


@pytest.mark.parametrize("policy", [
    {"mode": "deny"},
    {"mode": "allow_read"},
    {"mode": "require_approval"},
    {"require_mfa": True},
    {"risk": "high"},
    {"action": "update"},
    {"client_id": 2},
], ids=["deny", "read-only", "approval", "unverified-mfa", "wrong-risk", "wrong-action", "other-client"])
def test_mcp_create_needs_applicable_executable_ledger_policy(http_ledger, policy):
    http, db, payload = http_ledger
    if "client_id" in policy:
        db.add(models.Client(id=2, name="Other test client", general_settings={}))
        db.commit()
        db.add(models.AiOperationPolicy(
            client_id=2, resource="transactions", action="create", risk="medium", mode="allow_execute",
        ))
        db.commit()
    else:
        _open_gate(db, **policy)
    before = _snapshot(db)

    _assert_refused(http.post("/transactions/", json=payload, headers=MCP_HEADERS), "medium")

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

    _assert_refused(refused, "medium")
    assert _snapshot(db) == before

    _open_gate(db)
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

    monkeypatch.setattr(ai_policy_service, "_find_policy", fail_policy_lookup)

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
def test_every_mcp_ledger_write_needs_the_policy(http_ledger, path, body):
    # The paths beside /transactions that post journal legs check the same gate (§8-7).
    http, db, _ = http_ledger
    before = _snapshot(db)
    _assert_refused(http.post(path, json=body, headers=MCP_HEADERS), "medium")
    assert _snapshot(db) == before


@pytest.mark.parametrize("mcp_client_id", [None, ""])
def test_non_mcp_guard_returns_without_using_database(mcp_client_id):
    class NoDatabaseAccess:
        def query(self, *args, **kwargs):
            pytest.fail("A human write must not query AI policy")

    ai_policy_service.assert_direct_ledger_write_allowed(
        NoDatabaseAccess(), 1, mcp_client_id=mcp_client_id,
    )
