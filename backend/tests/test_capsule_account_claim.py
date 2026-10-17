"""Y2a: change an earmark without moving the account's money."""
import asyncio
from datetime import date
from unittest.mock import patch

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.domain.errors import DomainError, Invalid, NotFound
from app.domain.journal import Leg
from app.main import domain_error_handler
from app.routers import capsules as router
from app.services import capsule_service as capsule, ledger_service as ledger
from app.services.data_health_service import check_data_health
from app.workflows.capsule_workflow import set_account_claim


def post(db, amount, legs, currency="JPY"):
    tx = ledger.create_transaction(
        db, client_id=1, date=date.today(), description="Seed",
        amount_minor=amount, currency=currency, legs=legs,
    )
    db.flush()
    return tx


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                              poolclass=StaticPool)

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([
            models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"})
            for i in (1, 2)
        ])
        session.flush()
        session.add_all([
            models.Account(id=i, client_id=2 if i == 4 else 1, name=f"Account {i}",
                           account_type="expense" if i == 3 else "equity" if i == 5 else "asset")
            for i in range(1, 6)
        ])
        session.add_all([
            models.Capsule(id=i, client_id=2 if i == 3 else 1, name=f"Capsule {i}",
                           target_amount_minor=1000, monthly_contribution_minor=0,
                           funding_sources=[models.CapsuleFundingSource(
                               client_id=2 if i == 3 else 1, account_id=4 if i == 3 else 1,
                               target_amount_minor=1000)])
            for i in (1, 2, 3)
        ])
        session.flush()
        post(session, 1000, [Leg(1, debit=300, capsule_id=1), Leg(1, debit=700), Leg(5, credit=1000)])
        session.commit()
        yield session
    engine.dispose()


def adjust(db, target=600, **overrides):
    return set_account_claim(db, **{
        "client_id": 1, "capsule_id": 1, "account_id": 1, "target_amount": target, **overrides,
    })


def balance(db, account_id=1, currency="JPY"):
    return db.query(sa.func.sum(models.JournalEntry.debit_minor - models.JournalEntry.credit_minor)).join(
        models.Transaction,
    ).filter(models.JournalEntry.account_id == account_id, models.Transaction.currency == currency).scalar() or 0


@pytest.mark.parametrize("target,difference", [(600, 300), (125, -175), (0, -300), (1000, 700)])
def test_changes_only_claim_with_one_transaction(db, target, difference):
    assert adjust(db, target) == {"status": "ok", "claimed": float(target), "difference": float(difference)}
    assert capsule.claimed_minor(db, 1, 1, account_id=1) == ({"JPY": target} if target else {})
    assert balance(db) == 1000
    assert db.query(models.Transaction).count() == 2
    tx = db.query(models.Transaction).order_by(models.Transaction.id.desc()).first()
    assert tx.description == "確保額の調整: Capsule 1"
    assert tx.amount_minor == abs(difference) and tx.currency == "JPY"
    assert tx.date == date.today()
    assert [(leg.account_id, leg.debit_minor, leg.credit_minor, leg.capsule_id)
            for leg in sorted(tx.journal_entries, key=lambda leg: leg.sort_order)] == [
        (1, max(difference, 0), max(-difference, 0), 1),
        (1, max(-difference, 0), max(difference, 0), None),
    ]
    assert db.query(models.CapsuleDrawdown).count() == 0
    assert db.query(models.TransactionProposal).count() == 0


def test_equal_target_writes_nothing(db):
    with patch("app.workflows.capsule_workflow.invalidate_client") as invalidate:
        assert adjust(db, 300) == {"status": "unchanged", "claimed": 300.0, "difference": 0.0}
        invalidate.assert_not_called()
    assert db.query(models.Transaction).count() == 1
    assert not db.new and not db.dirty and not db.deleted


def test_attached_account_without_a_claim_can_start_at_zero(db):
    db.add(models.CapsuleFundingSource(client_id=1, capsule_id=1, account_id=2, target_amount_minor=0))
    post(db, 200, [Leg(2, debit=200), Leg(5, credit=200)])
    db.commit()
    assert adjust(db, 0, account_id=2) == {"status": "unchanged", "claimed": 0.0, "difference": 0.0}
    assert db.query(models.Transaction).count() == 2
    assert adjust(db, 125, account_id=2) == {"status": "ok", "claimed": 125.0, "difference": 125.0}
    assert balance(db, 2) == 200
    assert capsule.claimed_minor(db, 1, 1, account_id=1) == {"JPY": 300}


def test_adjustment_is_not_clamped_to_capsule_target(db):
    db.get(models.Capsule, 1).target_amount_minor = 100
    db.commit()
    assert adjust(db)["claimed"] == 600.0
    assert balance(db) == 1000


@pytest.mark.parametrize("target", [-1, -0.001, float("nan"), float("inf"), -float("inf"), 1001])
def test_invalid_amount_writes_nothing(db, target):
    with pytest.raises(Invalid):
        adjust(db, target)
    assert db.query(models.Transaction).count() == 1
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 300}
    assert balance(db) == 1000
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("overrides,error", [
    ({"account_id": 2}, Invalid),
    ({"account_id": 3}, Invalid),
    ({"account_id": 4}, NotFound),
    ({"account_id": 999}, NotFound),
    ({"capsule_id": 3}, NotFound),
    ({"capsule_id": 999}, NotFound),
    ({"client_id": 2}, NotFound),
])
def test_unavailable_account_or_capsule_writes_nothing(db, overrides, error):
    with pytest.raises(error):
        adjust(db, **overrides)
    assert db.query(models.Transaction).count() == 1
    assert db.query(models.CapsuleFundingSource).count() == 3
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("mixed", [False, True])
def test_foreign_account_currency_is_refused_without_fx(db, mixed):
    if not mixed:
        db.query(models.Transaction).one().currency = "USD"
    else:
        post(db, 10000, [Leg(1, debit=10000), Leg(5, credit=10000)], currency="USD")
    db.commit()
    count = db.query(models.Transaction).count()
    with pytest.raises(Invalid, match="通貨"):
        adjust(db)
    assert db.query(models.Transaction).count() == count


def test_foreign_claim_cannot_hide_behind_zero_foreign_balance(db):
    post(db, 100, [Leg(1, debit=100, capsule_id=1), Leg(1, credit=100)], currency="USD")
    db.commit()
    with pytest.raises(Invalid, match="通貨"):
        adjust(db)
    assert db.query(models.Transaction).count() == 2


def test_claims_on_other_accounts_and_capsules_are_preserved(db):
    db.add(models.CapsuleFundingSource(client_id=1, capsule_id=1, account_id=2, target_amount_minor=0))
    post(db, 200, [Leg(2, debit=200, capsule_id=1), Leg(5, credit=200)])
    post(db, 100, [Leg(1, debit=100, capsule_id=2), Leg(1, credit=100)])
    db.commit()
    adjust(db, 600)
    assert capsule.claimed_minor(db, 1, 1, account_id=1) == {"JPY": 600}
    assert capsule.claimed_minor(db, 1, 1, account_id=2) == {"JPY": 200}
    assert capsule.claimed_minor(db, 1, 2, account_id=1) == {"JPY": 100}
    assert balance(db) == 1000 and balance(db, 2) == 200


def test_other_capsules_already_use_part_of_the_balance(db):
    post(db, 500, [Leg(1, debit=500, capsule_id=2), Leg(1, credit=500)])
    db.commit()
    with pytest.raises(Invalid, match="残高"):
        adjust(db, 600)
    assert db.query(models.Transaction).count() == 2
    adjust(db, 500)
    issue = next(issue for issue in check_data_health(db, 1)["issues"]
                 if issue["code"] == "account_earmarked_beyond_its_balance")
    assert issue["count"] == 0


def test_raise_adds_no_data_health_issue(db):
    before = check_data_health(db, 1)["issues"]
    adjust(db)
    assert check_data_health(db, 1)["issues"] == before


def test_usd_claim_uses_cents_and_preserves_balance(db):
    db.get(models.Client, 1).general_settings = {"currency": "USD"}
    db.query(models.Transaction).one().currency = "USD"
    db.commit()
    assert adjust(db, 6.25) == {"status": "ok", "claimed": 6.25, "difference": 3.25}
    assert capsule.claimed_minor(db, 1, 1) == {"USD": 625}
    assert balance(db, currency="USD") == 1000
    assert db.query(models.Transaction).order_by(models.Transaction.id.desc()).first().amount_minor == 325


def test_commit_false_is_rollbackable_and_invalidates_only_on_commit(db):
    with patch("app.workflows.capsule_workflow.invalidate_client") as invalidate:
        adjust(db, commit=False)
        invalidate.assert_not_called()
        assert capsule.claimed_minor(db, 1, 1) == {"JPY": 600}
        db.rollback()
        assert capsule.claimed_minor(db, 1, 1) == {"JPY": 300}
        adjust(db)
        invalidate.assert_called_once_with(1)


def test_journal_failure_rolls_back_transaction(db):
    def refuse(*_):
        raise RuntimeError("journal failed")

    sa.event.listen(models.JournalEntry, "before_insert", refuse)
    try:
        with pytest.raises(RuntimeError, match="journal failed"):
            adjust(db)
    finally:
        sa.event.remove(models.JournalEntry, "before_insert", refuse)
    assert db.query(models.Transaction).count() == 1
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 300}
    assert balance(db) == 1000


def test_http_account_claim_and_client_isolation(db):
    app = FastAPI()
    app.include_router(router.router)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.dependency_overrides[router.database.get_db] = lambda: db
    app.dependency_overrides[router.dependencies.get_current_client] = lambda: db.get(models.Client, 1)

    async def request(http, capsule_id=1, account_id=1, target_amount=600):
        task = asyncio.create_task(http.post(f"/capsules/{capsule_id}/account-claim", json={
            "account_id": account_id, "target_amount": target_amount,
        }))
        deadline = asyncio.get_running_loop().time() + 30
        while not task.done():
            await asyncio.wait({task}, timeout=0.01)
            if asyncio.get_running_loop().time() >= deadline:
                task.cancel()
                pytest.fail("POST account-claim did not complete")
        return task.result()

    async def round_trip():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            response = await request(http)
            assert response.status_code == 200, response.text
            assert response.json() == {"status": "ok", "claimed": 600.0, "difference": 300.0}
            assert (await request(http)).json() == {"status": "unchanged", "claimed": 600.0, "difference": 0.0}
            assert (await request(http, target_amount=-1)).status_code == 400
            assert (await request(http, capsule_id=3)).status_code == 404
            assert (await request(http, account_id=4)).status_code == 404
            assert db.query(models.Transaction).count() == 2
            assert balance(db) == 1000

    asyncio.run(round_trip())
