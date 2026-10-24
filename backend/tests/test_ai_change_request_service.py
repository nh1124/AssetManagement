from __future__ import annotations

from app.services.money_storage import to_minor


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.domain.errors import Conflict, Refused
from backend.app.workflows.ai_change_request_workflow import (
    apply_change_request,
    approve_change_request,
    create_change_request,
    preview_change_request,
    refresh_preview,
    reject_change_request,
)
from backend.app.services.ai_policy_service import set_operation_mode
from backend.app.utils.password import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db):
    client = models.Client(
        id=1,
        name="Test User",
        username="tester",
        password_hash=hash_password("password123"),
        general_settings={},
    )
    db.add(client)
    # Every approval is confirmed with the authenticator code (WP36).
    db.add(models.ClientMfaSetting(client_id=1, enabled=True))
    db.commit()
    db.refresh(client)
    return client


# What /auth/reauth's step-up token decodes to for client 1.
STEP_UP = {"type": "step_up", "sub": "1"}

def _accounts(db):
    """A payment account and an expense account, which every entry now needs."""
    cash = models.Account(client_id=1, name="cash", account_type="asset")
    food = models.Account(client_id=1, name="food", account_type="expense")
    db.add_all([cash, food])
    db.commit()
    return cash, food


def test_transaction_change_request_preview_approve_apply() -> None:
    db = _session()
    try:
        client = _client(db)
        cash, food = _accounts(db)
        payload = schemas.AiChangeRequestCreate(
            resource="transactions",
            action="create",
            idempotency_key="tx-create-1",
            input_payload={
                "date": "2026-06-06",
                "description": "Lunch",
                "amount": 1200,
                "currency": "JPY",
                "from_account_id": cash.id,
                "to_account_id": food.id,
            },
        )

        preview = preview_change_request(db, client.id, payload)
        request = create_change_request(db, client.id, client.id, payload)
        pending_status = request.status
        approved = approve_change_request(db, client.id, client.id, request.id, STEP_UP)
        approved_status = approved.status
        applied = apply_change_request(db, client.id, client.id, request.id)

        assert preview["before_snapshot"] == {}
        assert preview["diff"]["count"] > 0
        assert pending_status == "pending"
        assert approved_status == "approved"
        assert applied.status == "applied"
        assert applied.result["proposal_id"]
        assert db.query(models.Transaction).filter(models.Transaction.client_id == client.id).count() == 0
        assert db.query(models.AiAuditLog).filter(models.AiAuditLog.approval_request_id == request.id).count() >= 1
    finally:
        db.close()


def test_change_request_idempotency_returns_existing_request() -> None:
    db = _session()
    try:
        client = _client(db)
        payload = schemas.AiChangeRequestCreate(
            resource="transactions",
            action="create",
            idempotency_key="same-key",
            input_payload={
                "date": "2026-06-06",
                "description": "Coffee",
                "amount": 500,
                "category": "food",
                "currency": "JPY",
            },
        )

        first = create_change_request(db, client.id, client.id, payload)
        second = create_change_request(db, client.id, client.id, payload)

        assert second.id == first.id
        assert db.query(models.AiChangeRequest).count() == 1
    finally:
        db.close()


def test_denied_policy_blocks_change_request_preview() -> None:
    db = _session()
    try:
        client = _client(db)
        set_operation_mode(db, client.id, "transactions.create", "deny", None)

        try:
            preview_change_request(
                db,
                client.id,
                schemas.AiChangeRequestPreviewRequest(
                    resource="transactions",
                    action="create",
                    input_payload={
                        "date": "2026-06-06",
                        "description": "Coffee",
                        "amount": 500,
                        "category": "food",
                        "currency": "JPY",
                    },
                ),
            )
        except Refused as exc:
            assert str(exc) == "This operation is not allowed for the AI in this client's settings."
            assert (exc.payload["error"], exc.payload["operation"]) == ("ai_operation_denied", "transactions.create")
            assert exc.payload["message"].in_language("ja") == "「取引を記録する」は AI 操作の権限で禁止されています。"
        else:
            raise AssertionError("Expected denied operation to be blocked")
    finally:
        db.close()


def test_recurring_transaction_change_request_apply() -> None:
    db = _session()
    try:
        client = _client(db)
        cash = models.Account(client_id=client.id, name="cash", account_type="asset")
        expense = models.Account(client_id=client.id, name="expense", account_type="expense")
        db.add_all([cash, expense]); db.flush()
        request = create_change_request(
            db,
            client.id,
            client.id,
            schemas.AiChangeRequestCreate(
                resource="auto_transactions",
                action="create",
                input_payload={
                    "name": "Rent", "source_account_id": cash.id, "destination_account_id": expense.id,
                    "amount": 100000,
                    "currency": "JPY",
                    "frequency": "Monthly",
                    "day_of_month": 25,
                    "kind": "expense", "repeat_mode": "indefinite", "start_date": "2026-10-01",
                    "is_active": True,
                },
            ),
        )
        approve_change_request(db, client.id, client.id, request.id, STEP_UP)
        applied = apply_change_request(db, client.id, client.id, request.id)

        assert applied.status == "applied"
        assert applied.result["registry_entry_id"]
        assert db.query(models.RegistryEntry).filter(models.RegistryEntry.client_id == client.id).count() == 1
    finally:
        db.close()


def test_monthly_plan_line_update_conflicts_after_target_change() -> None:
    db = _session()
    try:
        client = _client(db)
        line = models.MonthlyPlanLine(
            client_id=client.id,
            target_period="2026-06",
            line_type="expense",
            target_type="manual",
            name="Food",
            amount_minor=to_minor(30000, "JPY"),
            source="manual",
            source_kind="manual",
            identity_key="",
        )
        db.add(line)
        db.commit()
        db.refresh(line)

        request = create_change_request(
            db,
            client.id,
            client.id,
            schemas.AiChangeRequestCreate(
                resource="monthly_plan_lines",
                action="update",
                target_ref={"id": line.id},
                input_payload={"amount": 35000},
            ),
        )
        approve_change_request(db, client.id, client.id, request.id, STEP_UP)

        line.amount_minor = 32000
        db.commit()

        try:
            apply_change_request(db, client.id, client.id, request.id)
        except Conflict as exc:
            assert str(exc) == "Target changed after preview; refresh preview before applying"
            assert exc.payload == {
                "error": "precondition_conflict",
                "message": "Target changed after preview; refresh preview before applying",
            }
        else:
            raise AssertionError("Expected conflict")

        db.refresh(request)
        assert request.status == "failed"
        assert request.result["error"] == "precondition_conflict"

        # 作り直し (§8-5): rebuilt against today's 32000 it asks for approval again, then applies.
        rebuilt = refresh_preview(db, client.id, request.id)
        assert (rebuilt.status, rebuilt.approved_at) == ("pending", None)
        assert rebuilt.result == {"previous": {"error": "precondition_conflict",
                                                "message": "Target changed after preview; refresh preview before applying"}}
        assert [(change["before"], change["after"]) for change in rebuilt.diff["changes"] if change["field"] == "amount"] == [(32000, 35000)]
        approve_change_request(db, client.id, client.id, request.id, STEP_UP)
        assert apply_change_request(db, client.id, client.id, request.id).status == "applied"
        assert line.amount_minor == 35000
        # A decided request is not rebuilt.
        try:
            refresh_preview(db, client.id, request.id)
        except Exception as exc:
            assert "cannot be rebuilt from status applied" in str(exc)
        else:
            raise AssertionError("an applied request was rebuilt")
    finally:
        db.close()


def test_rebuilding_an_approved_request_asks_for_approval_again() -> None:
    db = _session()
    try:
        client = _client(db)
        line = models.MonthlyPlanLine(client_id=client.id, target_period="2026-06", line_type="expense", target_type="manual",
                                      name="Food", amount_minor=30000, source="manual", source_kind="manual", identity_key="")
        db.add(line)
        db.commit()
        request = create_change_request(db, client.id, client.id, schemas.AiChangeRequestCreate(
            resource="monthly_plan_lines", action="update", target_ref={"id": line.id}, input_payload={"amount": 35000}))
        approve_change_request(db, client.id, client.id, request.id, STEP_UP)
        assert refresh_preview(db, client.id, request.id).status == "pending"
        assert reject_change_request(db, client.id, request.id).status == "rejected"
    finally:
        db.close()


def test_approval_needs_the_code_and_a_denied_operation_cannot_be_applied() -> None:
    """WP36: approving always takes the step-up code; denying the operation later stops the apply."""
    db = _session()
    try:
        client = _client(db)
        line = models.MonthlyPlanLine(client_id=client.id, target_period="2026-06", line_type="expense", target_type="manual",
                                      name="Food", amount_minor=30000, source="manual", source_kind="manual", identity_key="")
        db.add(line)
        db.commit()
        request = create_change_request(db, client.id, client.id, schemas.AiChangeRequestCreate(
            resource="monthly_plan_lines", action="update", target_ref={"id": line.id}, input_payload={"amount": 35000}))
        assert request.risk == "medium"
        try:
            approve_change_request(db, client.id, client.id, request.id)
        except Refused as exc:
            assert exc.status_code == 401
        else:
            raise AssertionError("approved without the code")
        approve_change_request(db, client.id, client.id, request.id, STEP_UP)
        set_operation_mode(db, client.id, "plan_lines.update", "deny", None)
        try:
            apply_change_request(db, client.id, client.id, request.id)
        except Refused as exc:
            assert exc.payload["operation"] == "plan_lines.update"
        else:
            raise AssertionError("applied a denied operation")
        db.refresh(line)
        assert line.amount_minor == 30000
    finally:
        db.close()
