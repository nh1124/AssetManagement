"""The add_recurring monthly action creates a definition and its registry entry.

It passed the dropped ledger type to the model until 2026-10-10, so applying it
raised TypeError rather than creating anything. No stored action had ever used
the kind, so nothing failed in the open.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.action_bridge_service import apply_action
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.action_bridge_service import apply_action  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_applying_add_recurring_creates_the_definition_and_its_registry_entry() -> None:
    db = _session()
    try:
        db.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
        bank = models.Account(client_id=1, name="bank", account_type="asset", balance=100000)
        subs = models.Account(client_id=1, name="subscriptions", account_type="expense", balance=0)
        db.add_all([bank, subs])
        db.flush()
        action = models.MonthlyAction(
            client_id=1,
            source_period="2026-09",
            target_period="2026-10",
            proposal_id="add-recurring-1",
            idempotency_key="add-recurring-1",
            kind="add_recurring",
            status="pending",
            payload={
                "name": "a new subscription",
                "amount": 1200,
                "from_account_id": bank.id,
                "to_account_id": subs.id,
                "frequency": "Monthly",
                "day_of_month": 14,
            },
        )
        db.add(action)
        db.commit()

        result = apply_action(db, 1, action.id)

        recurring = db.query(models.RecurringTransaction).one()
        assert result["result"]["recurring_id"] == recurring.id
        assert (recurring.name, recurring.amount) == ("a new subscription", 1200)
        assert (recurring.from_account_id, recurring.to_account_id) == (bank.id, subs.id)
        assert recurring.currency == "JPY"
        assert recurring.next_due_date is not None

        # The registry is the place definitions are managed from, so the action
        # leaves one behind rather than an unlinked definition.
        entry = db.query(models.RegistryEntry).one()
        assert entry.source_recurring_transaction_id == recurring.id
        assert result["status"] == "applied"
    finally:
        db.close()


def test_pausing_deactivates_the_definition() -> None:
    db = _session()
    try:
        db.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
        registry_entry = models.RegistryEntry(
            client_id=1,
            name="recurring owner",
        )
        db.add(registry_entry)
        db.flush()
        recurring = models.RecurringTransaction(
            client_id=1,
            source_registry_entry_id=registry_entry.id,
            name="a subscription",
            amount=1200,
            currency="JPY",
            frequency="Monthly",
            day_of_month=14,
            next_due_date=date(2026, 10, 14),
            is_active=True,
        )
        db.add(recurring)
        db.flush()
        action = models.MonthlyAction(
            client_id=1,
            source_period="2026-09",
            target_period="2026-10",
            proposal_id="pause-recurring-1",
            idempotency_key="pause-recurring-1",
            kind="pause_recurring",
            status="pending",
            payload={"recurring_id": recurring.id},
        )
        db.add(action)
        db.commit()

        apply_action(db, 1, action.id)

        db.refresh(recurring)
        assert recurring.is_active is False
    finally:
        db.close()
