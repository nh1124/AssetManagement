from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.services.ai_change_request_service import (
    apply_change_request,
    approve_change_request,
    create_change_request,
    preview_change_request,
)
from backend.app.services.ai_policy_service import replace_client_policies
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
        ai_config={},
        general_settings={},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def test_transaction_change_request_preview_approve_apply() -> None:
    db = _session()
    try:
        client = _client(db)
        payload = schemas.AiChangeRequestCreate(
            resource="transactions",
            action="create",
            risk="medium",
            idempotency_key="tx-create-1",
            input_payload={
                "date": "2026-06-06",
                "description": "Lunch",
                "amount": 1200,
                "type": "Expense",
                "category": "food",
                "currency": "JPY",
            },
        )

        preview = preview_change_request(db, client.id, payload)
        request = create_change_request(db, client.id, client.id, payload)
        pending_status = request.status
        approved = approve_change_request(db, client.id, client.id, request.id)
        approved_status = approved.status
        applied = apply_change_request(db, client.id, client.id, request.id)

        assert preview["before_snapshot"] == {}
        assert preview["diff"]["count"] > 0
        assert pending_status == "pending"
        assert approved_status == "approved"
        assert applied.status == "applied"
        assert applied.result["transaction_id"]
        assert db.query(models.Transaction).filter(models.Transaction.client_id == client.id).count() == 1
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
            risk="medium",
            idempotency_key="same-key",
            input_payload={
                "date": "2026-06-06",
                "description": "Coffee",
                "amount": 500,
                "type": "Expense",
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
        replace_client_policies(db, client.id, [{
            "resource": "transactions",
            "action": "create",
            "risk": "medium",
            "mode": "deny",
            "require_mfa": False,
        }])

        try:
            preview_change_request(
                db,
                client.id,
                schemas.AiChangeRequestPreviewRequest(
                    resource="transactions",
                    action="create",
                    risk="medium",
                    input_payload={
                        "date": "2026-06-06",
                        "description": "Coffee",
                        "amount": 500,
                        "type": "Expense",
                        "category": "food",
                        "currency": "JPY",
                    },
                ),
            )
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("Expected denied operation to be blocked")
    finally:
        db.close()


def test_recurring_transaction_change_request_apply() -> None:
    db = _session()
    try:
        client = _client(db)
        request = create_change_request(
            db,
            client.id,
            client.id,
            schemas.AiChangeRequestCreate(
                resource="recurring_transactions",
                action="create",
                risk="medium",
                input_payload={
                    "name": "Rent",
                    "amount": 100000,
                    "currency": "JPY",
                    "type": "Expense",
                    "frequency": "Monthly",
                    "day_of_month": 25,
                    "auto_post": True,
                    "is_active": True,
                },
            ),
        )
        approve_change_request(db, client.id, client.id, request.id)
        applied = apply_change_request(db, client.id, client.id, request.id)

        assert applied.status == "applied"
        assert applied.result["recurring_transaction_id"]
        assert db.query(models.RecurringTransaction).filter(models.RecurringTransaction.client_id == client.id).count() == 1
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
            amount=30000,
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
                risk="medium",
                target_ref={"id": line.id},
                input_payload={"amount": 35000},
            ),
        )
        approve_change_request(db, client.id, client.id, request.id)

        line.amount = 32000
        db.commit()

        try:
            apply_change_request(db, client.id, client.id, request.id)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("Expected conflict")

        db.refresh(request)
        assert request.status == "failed"
        assert request.result["error"] == "precondition_conflict"
    finally:
        db.close()
