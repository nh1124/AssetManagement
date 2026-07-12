from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.routers import data_transfer, transactions as transaction_router
from backend.app.services import ai_change_request_service, report_service
from backend.app.services.ai_change_request_service import (
    apply_change_request,
    approve_change_request,
    create_change_request,
)
from backend.app.utils.password import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db) -> models.Client:
    client = models.Client(
        id=1,
        name="Test User",
        username="atomicity-test",
        password_hash=hash_password("password123"),
        ai_config={},
        general_settings={},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def _raise_journal_failure(*_args, **_kwargs) -> None:
    raise ValueError("forced journal failure")


def test_create_transaction_rolls_back_when_journal_posting_fails(monkeypatch) -> None:
    db = _session()
    try:
        client = _client(db)
        monkeypatch.setattr(transaction_router, "post_transaction_journal", _raise_journal_failure)

        with pytest.raises(ValueError, match="forced journal failure"):
            transaction_router.create_transaction(
                schemas.TransactionCreate(
                    date=date(2026, 7, 1),
                    description="Atomic lunch",
                    amount=1200,
                    type="Expense",
                    category="food",
                    currency="JPY",
                ),
                db=db,
                current_client=client,
            )

        assert db.query(models.Transaction).count() == 0
        assert db.query(models.JournalEntry).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize("period_kind", ["monthly", "range"])
def test_report_goal_allocation_rolls_back_when_journal_posting_fails(monkeypatch, period_kind: str) -> None:
    db = _session()
    try:
        client = _client(db)
        goal = models.LifeEvent(
            client_id=client.id,
            name="Emergency fund",
            target_date=date(2027, 12, 31),
            target_amount=500000,
            priority=1,
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        proposal = {
            "id": "allocate-emergency",
            "kind": "allocate_to_goal",
            "description": "Allocate to emergency fund",
            "amount": 10000,
            "target_id": goal.id,
            "auto_executable": True,
        }
        monkeypatch.setattr(report_service, "post_transaction_journal", _raise_journal_failure)

        if period_kind == "monthly":
            monkeypatch.setattr(
                report_service,
                "generate_monthly_report",
                lambda *_args, **_kwargs: {"action_proposals": [proposal]},
            )
            apply = lambda: report_service.apply_monthly_report_proposal(
                db, client.id, "2026-07", proposal["id"]
            )
        else:
            monkeypatch.setattr(
                report_service,
                "generate_period_report",
                lambda *_args, **_kwargs: {
                    "period": "2026-07-01_to_2026-07-31",
                    "action_proposals": [proposal],
                },
            )
            apply = lambda: report_service.apply_period_report_proposal(
                db,
                client.id,
                date(2026, 7, 1),
                date(2026, 7, 31),
                proposal["id"],
            )

        with pytest.raises(ValueError, match="forced journal failure"):
            apply()

        assert db.query(models.Transaction).count() == 0
        assert db.query(models.JournalEntry).count() == 0
        assert db.query(models.Capsule).count() == 0
        assert db.query(models.CapsuleHolding).count() == 0
        assert db.query(models.MonthlyAction).count() == 0
    finally:
        db.close()


def test_report_goal_allocation_commits_journal_and_capsule(monkeypatch) -> None:
    db = _session()
    try:
        client = _client(db)
        goal = models.LifeEvent(
            client_id=client.id,
            name="Emergency fund",
            target_date=date(2027, 12, 31),
            target_amount=500000,
            priority=1,
        )
        db.add(goal)
        db.flush()
        capsule = models.Capsule(
            client_id=client.id,
            life_event_id=goal.id,
            name=goal.name,
            target_amount=goal.target_amount,
            monthly_contribution=0,
            current_balance=0,
            capsule_type="life_event",
            target_amount_source="life_event",
            monthly_contribution_source="manual",
        )
        db.add(capsule)
        db.flush()
        db.add(models.CapsuleRule(
            client_id=client.id,
            capsule_id=capsule.id,
            trigger_type="Transfer",
            source_mode="transaction_account",
            amount_type="fixed",
            amount_value=1000,
            is_active=True,
        ))
        db.commit()
        db.refresh(goal)
        proposal = {
            "id": "allocate-emergency-success",
            "kind": "allocate_to_goal",
            "description": "Allocate to emergency fund",
            "amount": 10000,
            "target_id": goal.id,
            "auto_executable": True,
        }
        monkeypatch.setattr(
            report_service,
            "generate_monthly_report",
            lambda *_args, **_kwargs: {"action_proposals": [proposal]},
        )

        result = report_service.apply_monthly_report_proposal(
            db, client.id, "2026-07", proposal["id"]
        )

        assert result["status"] == "applied"
        assert db.query(models.Transaction).count() == 1
        assert db.query(models.JournalEntry).count() == 2
        assert db.query(models.MonthlyAction).filter_by(status="applied").count() == 1
        capsule = db.query(models.Capsule).filter_by(life_event_id=goal.id).one()
        holding = db.query(models.CapsuleHolding).filter_by(capsule_id=capsule.id).one()
        assert holding.held_amount == 10000
    finally:
        db.close()


def _approved_transaction_change_request(db, client: models.Client) -> models.AiChangeRequest:
    request = create_change_request(
        db,
        client.id,
        client.id,
        schemas.AiChangeRequestCreate(
            resource="transactions",
            action="create",
            risk="medium",
            idempotency_key="atomic-ai-transaction",
            input_payload={
                "date": "2026-07-01",
                "description": "AI lunch",
                "amount": 900,
                "type": "Expense",
                "category": "food",
                "currency": "JPY",
            },
        ),
    )
    return approve_change_request(db, client.id, client.id, request.id)


def test_ai_apply_rolls_back_transaction_when_journal_posting_fails(monkeypatch) -> None:
    db = _session()
    try:
        client = _client(db)
        request = _approved_transaction_change_request(db, client)
        monkeypatch.setattr(ai_change_request_service, "post_transaction_journal", _raise_journal_failure)

        with pytest.raises(HTTPException) as exc_info:
            apply_change_request(db, client.id, client.id, request.id)

        assert exc_info.value.status_code == 400
        assert db.query(models.Transaction).count() == 0
        assert db.query(models.JournalEntry).count() == 0
        db.refresh(request)
        assert request.status == "failed"
    finally:
        db.close()


def test_ai_apply_same_request_does_not_create_duplicate_transaction() -> None:
    db = _session()
    try:
        client = _client(db)
        request = _approved_transaction_change_request(db, client)

        first = apply_change_request(db, client.id, client.id, request.id)
        first_transaction_id = first.result["transaction_id"]
        second = apply_change_request(db, client.id, client.id, request.id)

        assert second.result["transaction_id"] == first_transaction_id
        assert db.query(models.Transaction).count() == 1
        assert db.query(models.JournalEntry).count() == 2
    finally:
        db.close()


def test_import_validation_and_import_reject_missing_journal_entries() -> None:
    db = _session()
    try:
        client = _client(db)
        existing = models.Account(client_id=client.id, name="existing", account_type="asset")
        db.add(existing)
        db.commit()
        payload = data_transfer.ImportPayload(
            version=data_transfer.EXPORT_VERSION,
            data={
                "accounts": [
                    {"id": 10, "name": "cash", "account_type": "asset"},
                    {"id": 11, "name": "food", "account_type": "expense"},
                ],
                "transactions": [
                    {
                        "id": 20,
                        "date": "2026-07-01",
                        "description": "Missing journal",
                        "amount": 1000,
                        "type": "Expense",
                        "from_account_id": 10,
                        "to_account_id": 11,
                    }
                ],
                "journal_entries": [],
            },
        )

        validation = data_transfer.validate_import_client_data(payload, current_client=client)
        assert validation["status"] == "invalid"
        assert any(issue["code"] == "journal_entries_missing" for issue in validation["issues"])

        with pytest.raises(HTTPException) as exc_info:
            data_transfer.import_client_data(payload, db=db, current_client=client)

        assert exc_info.value.status_code == 400
        assert db.query(models.Account).filter_by(id=existing.id).one().name == "existing"
        assert db.query(models.Transaction).count() == 0
    finally:
        db.close()


def test_delete_transaction_rolls_back_reversal_and_rows_when_commit_fails(monkeypatch) -> None:
    db = _session()
    try:
        client = _client(db)
        cash = models.Account(client_id=client.id, name="cash", account_type="asset", balance=-1000)
        food = models.Account(client_id=client.id, name="food", account_type="expense", balance=1000)
        db.add_all([cash, food])
        db.flush()
        transaction = models.Transaction(
            client_id=client.id,
            date=date(2026, 7, 1),
            description="Delete rollback",
            amount=1000,
            type="Expense",
            from_account_id=cash.id,
            to_account_id=food.id,
        )
        db.add(transaction)
        db.flush()
        db.add_all(
            [
                models.JournalEntry(transaction_id=transaction.id, account_id=food.id, debit=1000, credit=0),
                models.JournalEntry(transaction_id=transaction.id, account_id=cash.id, debit=0, credit=1000),
            ]
        )
        db.commit()
        transaction_id = transaction.id

        monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")))
        with pytest.raises(RuntimeError, match="forced commit failure"):
            transaction_router.delete_transaction(transaction_id, db=db, current_client=client)

        assert db.query(models.Transaction).filter_by(id=transaction_id).count() == 1
        assert db.query(models.JournalEntry).filter_by(transaction_id=transaction_id).count() == 2
        db.refresh(cash)
        db.refresh(food)
        assert cash.balance == -1000
        assert food.balance == 1000
    finally:
        db.close()
