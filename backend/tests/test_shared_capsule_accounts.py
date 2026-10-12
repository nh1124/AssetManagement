"""F0: an account two capsules reserve into is counted once, and reported.

A capsule's reservation is the balance of the account it reserves into, so the
earmarked total used to add that balance once per capsule: three capsules on an
account holding 100,000 reported 300,000 earmarked and logical_balance was
200,000 too low. Nothing prevents the arrangement -- capsules.account_id has no
unique constraint and no service refuses it -- so this was reachable.

capsule_funding_design.md replaces the whole-balance reading with the sum of
the claims on each account. These tests hold the two halves of the interim
state: the figure is no longer multiplied, and data_health says the
arrangement is wrong rather than leaving it to be inferred from a total.
"""
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
from app.services.data_health_service import check_data_health

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
def test_a_shared_account_is_counted_once_however_many_capsules_hold_it(db, count):
    session, _, pooled_account = db
    _capsules(session, pooled_account, [f"Capsule {i}" for i in range(count)])
    # Not count * HELD, which is what this returned before F0.
    assert _sum_capsule_balance(session, 1) == HELD


def test_two_accounts_are_both_counted(db):
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
    assert _sum_capsule_balance(session, 1) == HELD + 7000


def test_an_unbound_capsule_still_reports_its_legacy_cache(db):
    session, _, _ = db
    capsule = models.Capsule(client_id=1, name="Unbound", target_amount_minor=0,
                             monthly_contribution_minor=0, current_balance_minor=0)
    session.add(capsule)
    session.commit()
    assert _sum_capsule_balance(session, 1) == 0


def test_data_health_reports_the_shared_account_and_names_its_capsules(db):
    session, _, pooled_account = db
    _capsules(session, pooled_account, ["Wedding", "Car"])
    issue = next(item for item in check_data_health(session, 1)["issues"]
                 if item["code"] == "capsules_sharing_an_account")
    assert issue["severity"] == "error"
    assert issue["repairable"] is False
    assert issue["count"] == 1
    assert issue["items"] == [{
        "account_id": pooled_account.id,
        "account_name": "Pooled",
        "capsule_count": 2,
        "capsules": ["Car", "Wedding"],
    }]


def test_data_health_is_silent_when_every_capsule_has_its_own_account(db):
    session, cash, pooled_account = db
    own = models.Account(client_id=1, name="Own pool", account_type="asset", role="earmarked")
    session.add(own)
    session.commit()
    _capsules(session, pooled_account, ["Wedding"])
    capsule_service.create_capsule(session, 1, schemas.CapsuleCreate(
        name="Car", target_amount=50000, monthly_contribution=0, account_id=own.id,
    ))
    session.commit()
    issue = next(item for item in check_data_health(session, 1)["issues"]
                 if item["code"] == "capsules_sharing_an_account")
    assert (issue["count"], issue["items"]) == (0, [])


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
