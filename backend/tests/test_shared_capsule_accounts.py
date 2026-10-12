"""Shared accounts are supported; only attributed movements are earmarked."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.domain.money import Money
from app.services import capsule_service, ledger_service
from app.services.analysis_service import _sum_capsule_balance

WHEN = date(2026, 10, 12)
HELD = 100000


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(id=1, name="shared", username="shared",
                              general_settings={"currency": "JPY"}, ai_config={}))
    cash = models.Account(client_id=1, name="Cash", account_type="asset", role="operating")
    pooled = models.Account(client_id=1, name="Pooled", account_type="asset", role="earmarked")
    session.add_all([cash, pooled])
    session.commit()
    ledger_service.create_transaction(
        session, client_id=1, date=WHEN, description="Into the pool",
        amount_minor=Money.from_major(str(HELD), "JPY").minor, currency="JPY",
        from_account_id=cash.id, to_account_id=pooled.id,
    )
    session.commit()
    try:
        yield session, cash, pooled
    finally:
        session.close()
        engine.dispose()


def _capsules(db, pooled, names, *, target=50000):
    for name in names:
        capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(
            name=name, target_amount=target, monthly_contribution=10000,
            account_id=pooled.id,
        ))
    db.commit()


@pytest.mark.parametrize("count", [1, 2, 3])
def test_unattributed_shared_balance_is_never_a_capsule_claim(db, count):
    session, _, pooled_account = db
    _capsules(session, pooled_account, [f"Capsule {i}" for i in range(count)])
    assert _sum_capsule_balance(session, 1) == 0


def test_unattributed_balance_on_two_accounts_is_not_earmarked(db):
    session, cash, pooled_account = db
    second = models.Account(client_id=1, name="Second pool", account_type="asset", role="earmarked")
    session.add(second)
    session.commit()
    ledger_service.create_transaction(
        session, client_id=1, date=WHEN, description="Into the second pool",
        amount_minor=Money.from_major("7000", "JPY").minor, currency="JPY",
        from_account_id=cash.id, to_account_id=second.id,
    )
    session.commit()
    _capsules(session, pooled_account, ["Shared A", "Shared B"])
    capsule_service.create_capsule(session, 1, schemas.CapsuleCreate(
        name="Own", target_amount=50000, monthly_contribution=0, account_id=second.id,
    ))
    session.commit()
    assert _sum_capsule_balance(session, 1) == 0


def test_an_unbound_capsule_ignores_its_legacy_cache(db):
    session, _, _ = db
    capsule = models.Capsule(client_id=1, name="Unbound", target_amount_minor=0,
                             monthly_contribution_minor=0)
    session.add(capsule)
    session.commit()
    assert _sum_capsule_balance(session, 1) == 0


def test_sharing_an_account_no_longer_stops_the_rules_firing(db):
    """F1b fixes the bug F0 pinned: shared balance is not one's own claim.

    Previously all three read the whole shared balance and proposed nothing.
    With no attributed reservations yet, each still has its own full headroom.
    """
    session, cash, pooled_account = db
    _capsules(session, pooled_account, ["Wedding", "Car", "Travel"], target=50000)
    for capsule in session.query(models.Capsule).all():
        session.add(models.CapsuleRule(
            client_id=1, capsule_id=capsule.id, trigger_type="Income",
            source_mode="fixed_account", source_account_id=cash.id,
            amount_type="fixed", amount_minor=10000, is_active=True,
        ))
    session.commit()
    income = models.Account(client_id=1, name="Salary", account_type="income")
    session.add(income)
    session.flush()
    salary = ledger_service.create_transaction(
        session, client_id=1, date=WHEN, description="Salary",
        amount_minor=Money.from_major("200000", "JPY").minor, currency="JPY",
        from_account_id=income.id,
        to_account_id=cash.id,
    )
    session.flush()
    specs = capsule_service.capsule_transfer_specs(
        session, 1, entries=list(salary.journal_entries),
        description="Salary", amount=200000, currency="JPY",
    )
    assert len(specs) == 3
    assert [spec.amount_minor for spec in specs] == [10000, 10000, 10000]
    assert {spec.destination_account_id for spec in specs} == {pooled_account.id}
