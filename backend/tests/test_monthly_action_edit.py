"""Y3b: pending actions can be corrected without rewriting completed decisions."""
import asyncio
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.domain.errors import DomainError, Refused
from app.main import domain_error_handler
from app.routers import actions as router
from app.services import monthly_action_store as store
from app.workflows import monthly_action_workflow as workflow


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([
            models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"})
            for i in (1, 2)
        ])
        session.add_all([
            models.Account(id=i, client_id=1, name=f"支出 {i}", account_type="expense")
            for i in (1, 2)
        ])
        session.add(models.BudgetPlan(id=1, client_id=1, name="基本予算", is_default=True))
        session.commit()
        yield session
    engine.dispose()


def fields(**overrides):
    return {
        "source_period": "2026-09", "target_period": "2026-10", "kind": "set_budget",
        "description": "支出予算", "payload": {"account_id": 1, "amount": 1000}, **overrides,
    }


def create(db, client_id=1, status="pending"):
    result = workflow.create_action(db, client_id, **fields())
    row = store.get(db, client_id, result["id"])
    row.status = status
    if status == "applied":
        row.applied_at = datetime(2026, 10, 1)
        row.result = {"plan_line_id": 17}
    db.commit()
    return row.id


def request(db, method, path, body=None):
    app = FastAPI()
    app.include_router(router.router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.dependency_overrides[router.get_db] = lambda: db
    app.dependency_overrides[router.get_current_client] = lambda: db.get(models.Client, 1)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            task = asyncio.create_task(http.request(method, path, json=body))
            # Polling keeps the sandbox's worker-thread completion notifications moving.
            deadline = asyncio.get_running_loop().time() + 30
            while not task.done():
                await asyncio.wait({task}, timeout=0.01)
                if asyncio.get_running_loop().time() >= deadline:
                    task.cancel()
                    pytest.fail(f"{method} {path} did not complete")
            return task.result()

    return asyncio.run(run())


def snapshot(db, action_id, client_id=1):
    db.expire_all()
    return workflow.action_to_dict(store.get(db, client_id, action_id))


def test_edit_pending_updates_fields_and_preserves_identity_and_status(db):
    action_id = create(db)
    before = snapshot(db, action_id)
    key = store.get(db, 1, action_id).idempotency_key
    body = fields(source_period="2026-10", target_period="2026-12", kind="change_capsule_contribution",
                  description="積立を修正", payload={"capsule_id": 3, "monthly_contribution": 2500})
    response = request(db, "PUT", f"/actions/{action_id}", body)
    assert response.status_code == 200, response.text
    after = response.json()
    assert all(after[name] == value for name, value in body.items())
    assert (after["amount"], after["target_id"]) == (2500, 3)
    for name in ("id", "proposal_id", "status", "created_at", "applied_at", "result"):
        assert after[name] == before[name]
    assert store.get(db, 1, action_id).idempotency_key == key
    assert after == snapshot(db, action_id)
    assert request(db, "GET", "/actions/").json() == [after]


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("status,label", [("applied", "実行済み"), ("skipped", "見送り"), ("failed", "失敗")])
def test_non_pending_mutations_are_refused_without_changes(db, method, status, label):
    action_id = create(db, status=status)
    before = snapshot(db, action_id)
    response = request(db, method, f"/actions/{action_id}", fields(description="修正") if method == "PUT" else None)
    assert response.status_code == 422, response.text
    assert label in response.json()["detail"]
    assert snapshot(db, action_id) == before
    assert not db.dirty and not db.deleted and not db.new


def test_pending_guard_raises_project_refused(db):
    action_id = create(db, status="applied")
    with pytest.raises(Refused) as error:
        workflow.update_action(db, 1, action_id, **fields())
    assert error.value.status_code == 422


def test_delete_pending_removes_only_selected_action(db):
    action_id = create(db)
    other_id = create(db)
    response = request(db, "DELETE", f"/actions/{action_id}")
    assert response.status_code == 200, response.text
    assert store.get(db, 1, action_id) is None
    assert store.get(db, 1, other_id).status == "pending"


@pytest.mark.parametrize("body,status", [
    (fields(kind="unsupported"), 400),
    (fields(payload={"account_id": 1, "amount": "NaN"}), 400),
    (fields(source_period="invalid", target_period=None), 400),
    (fields(payload=[]), 422),
    ({"source_period": "2026-09", "kind": "set_budget"}, 422),
])
def test_invalid_update_uses_create_validation_and_writes_nothing(db, body, status):
    action_id = create(db)
    before = snapshot(db, action_id)
    created = request(db, "POST", "/actions/", body)
    updated = request(db, "PUT", f"/actions/{action_id}", body)
    assert created.status_code == updated.status_code == status, (created.text, updated.text)
    assert created.json()["detail"] == updated.json()["detail"]
    assert snapshot(db, action_id) == before
    assert db.query(models.MonthlyAction).count() == 1
    assert not db.dirty and not db.new


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("client_id", [1, 2])
def test_routes_hide_missing_and_other_clients_actions(db, method, client_id):
    action_id = create(db, client_id=client_id)
    before = snapshot(db, action_id, client_id)
    target_id = action_id if client_id == 2 else action_id + 999
    response = request(db, method, f"/actions/{target_id}", fields() if method == "PUT" else None)
    assert response.status_code == 404, response.text
    assert snapshot(db, action_id, client_id) == before


def test_apply_edited_action_uses_new_payload_and_target_period(db):
    action_id = create(db)
    body = fields(target_period="2027-01", payload={"account_id": 2, "amount": 3456, "plan_id": 1})
    response = request(db, "PUT", f"/actions/{action_id}", body)
    assert response.status_code == 200, response.text
    applied = request(db, "POST", f"/actions/{action_id}/apply")
    assert applied.status_code == 200, applied.text
    line = db.query(models.MonthlyPlanLine).one()
    assert (line.account_id, line.amount, line.target_period) == (2, 3456, "2027-01")
    assert applied.json()["payload"] == body["payload"]
    assert applied.json()["status"] == "applied"


def test_update_keeps_create_defaults_and_money_conversion(db):
    db.get(models.Client, 1).general_settings = {"currency": "USD"}
    db.commit()
    action_id = create(db)
    body = fields(source_period="2026-12", target_period=None, description="",
                  payload={"account_id": 2, "amount": 12.34})
    response = request(db, "PUT", f"/actions/{action_id}", body)
    assert response.status_code == 200, response.text
    assert response.json()["target_period"] == "2027-01"
    assert response.json()["description"] == "set budget"
    assert response.json()["amount"] == 12.34
    assert store.get(db, 1, action_id).amount_minor == 1234
