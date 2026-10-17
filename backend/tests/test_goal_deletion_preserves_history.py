from __future__ import annotations

from scenario_fixtures import goal_scenario_id

from app.services.money_storage import to_minor


from backend.app.domain.money import Money

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.domain.journal import Leg
    from backend.app.domain.errors import Refused
    from backend.app.routers.life_events import delete_life_event
    from backend.app.services import ledger_service
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.domain.journal import Leg
    from app.domain.errors import Refused  # type: ignore[no-redef]
    from app.routers.life_events import delete_life_event  # type: ignore[no-redef]
    from app.services import ledger_service  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )()


def _setup(db, *, claimed_amount=0):
    client = models.Client(
        id=1,
        name="goal-deletion-test",
        general_settings={},
        ai_config={},
    )
    earmarked = models.Account(
        client_id=client.id,
        name="Goal funds",
        account_type="asset",
        is_active=True,
    )
    income = models.Account(
        client_id=client.id,
        name="Income",
        account_type="income",
    )
    destination = models.Account(
        client_id=client.id,
        name="Cash",
        account_type="asset",
    )
    goal = models.LifeEvent(scenario_id=goal_scenario_id(db, client.id),
        client_id=client.id,
        name="Emergency fund",
        target_date=date(2027, 12, 31),
        target_amount_minor=to_minor(500, "JPY"),
        priority=1,
    )
    db.add_all([client, earmarked, income, destination, goal])
    db.flush()
    capsule = models.Capsule(
        client_id=client.id,
        life_event_id=goal.id,
        funding_sources=[models.CapsuleFundingSource(client_id=client.id, account_id=earmarked.id, target_amount_minor=to_minor(500, "JPY") or 0)],
        name=goal.name,
        target_amount_minor=to_minor(500, "JPY"),
        monthly_contribution_minor=to_minor(0, "JPY"),
        capsule_type="life_event",
        target_amount_source="life_event",
        monthly_contribution_source="manual",
    )
    db.add(capsule)
    db.flush()
    if claimed_amount:
        ledger_service.create_transaction(
            db, client_id=client.id, date=date(2026, 10, 11), description="Reserve for goal",
            amount_minor=claimed_amount, currency="JPY",
            legs=[Leg(earmarked.id, debit=claimed_amount, capsule_id=capsule.id), Leg(income.id, credit=claimed_amount)],
        )
    db.commit()
    return client, goal, earmarked, income, destination


def _assert_transactions_balance(db):
    for transaction in db.query(models.Transaction).all():
        entries = db.query(models.JournalEntry).filter_by(
            transaction_id=transaction.id,
        ).all()
        debits = sum(entry.debit for entry in entries)
        credits = sum(entry.credit for entry in entries)
        assert debits == credits, (transaction.id, debits, credits)


def test_goal_deletion_preserves_ledger_history():
    db = _session()
    try:
        client, goal, earmarked, income, _ = _setup(db)
        transaction = ledger_service.create_transaction(
            db,
            client_id=client.id,
            date=date(2026, 10, 11),
            description="Fund goal through ledger",
            amount_minor=Money.from_major(str(500), "JPY").minor,
            currency="JPY",
            from_account_id=income.id,
            to_account_id=earmarked.id,
        )
        db.commit()
        transaction_id = transaction.id
        account_id = earmarked.id
        entry_ids = {entry.id for entry in db.query(models.JournalEntry).all()}
        assert len(entry_ids) == 2

        delete_life_event(
            goal.id,
            transfer_account_id=None,
            db=db,
            current_client=client,
        )
        db.expire_all()

        assert db.query(models.Transaction).one().id == transaction_id
        _assert_transactions_balance(db)
        assert {entry.id for entry in db.query(models.JournalEntry).all()} == entry_ids
        account = db.get(models.Account, account_id)
        assert account is not None
        assert account.is_active is False
    finally:
        db.close()


def test_goal_deletion_removes_empty_earmarked_account():
    db = _session()
    try:
        client, goal, earmarked, _, _ = _setup(db)
        account_id = earmarked.id

        delete_life_event(
            goal.id,
            transfer_account_id=None,
            db=db,
            current_client=client,
        )
        db.expire_all()

        assert db.get(models.Account, account_id) is None
        assert db.query(models.JournalEntry).count() == 0
    finally:
        db.close()


def test_goal_deletion_requires_destination_for_capsule_claim():
    db = _session()
    try:
        client, goal, _, _, _ = _setup(db, claimed_amount=500)

        with pytest.raises(Refused) as exc_info:
            delete_life_event(
                goal.id,
                transfer_account_id=None,
                db=db,
                current_client=client,
            )

        assert exc_info.value.status_code == 422
        assert str(exc_info.value) == "transfer_account_id is required because one or more capsules have a non-zero balance."
        assert db.get(models.LifeEvent, goal.id) is not None
        assert db.query(models.JournalEntry).filter(models.JournalEntry.capsule_id.is_not(None)).one().debit_minor == 500
        assert db.query(models.JournalEntry).count() == 2
    finally:
        db.close()


def test_goal_deletion_transfers_capsule_claim():
    db = _session()
    try:
        client, goal, _, _, destination = _setup(db, claimed_amount=500)
        destination_id = destination.id

        delete_life_event(
            goal.id,
            transfer_account_id=destination_id,
            db=db,
            current_client=client,
        )
        db.expire_all()

        transaction = db.query(models.Transaction).filter(models.Transaction.description.like("Goal deleted%")).one()
        assert transaction.description == "Goal deleted – funds returned from Capsule: Emergency fund"
        _assert_transactions_balance(db)
        entries = db.query(models.JournalEntry).filter_by(
            account_id=destination_id,
        ).all()
        assert sum(entry.debit for entry in entries) - sum(entry.credit for entry in entries) == 500
        assert db.query(models.JournalEntry).count() == 4
    finally:
        db.close()
