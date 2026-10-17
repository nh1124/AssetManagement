"""Account earmarks expose attached capsules' own journal claims in client currency."""
import asyncio
from datetime import date

from fastapi import FastAPI
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.domain.journal import Leg
from app.routers import accounts as router
from app.services import capsule_service, ledger_service


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"})
            for i in [1, 2]
        ])
        session.flush()
        session.add_all([
            models.Account(id=i, client_id=1 if i < 4 else 2, name=f"Account {i}", account_type="asset")
            for i in [1, 2, 3, 4]
        ])
        session.flush()
        session.add_all([
            models.Capsule(id=i, client_id=1, name=f"Capsule {i}",
                           funding_sources=[models.CapsuleFundingSource(
                               client_id=1, account_id=2, target_amount_minor=0,
                               max_share_bp=0 if i == 3 else i * 2000,
                           )])
            for i in [1, 2, 3]
        ])
        session.commit()
        yield session
    engine.dispose()


def post(db, amount, legs, currency="JPY"):
    ledger_service.create_transaction(db, client_id=1, date=date(2026, 10, 14),
                                      description="Test claim", amount_minor=amount,
                                      currency=currency, legs=legs)
    db.commit()


def get(db, account_id):
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[router.get_db] = lambda: db
    app.dependency_overrides[router.get_current_client] = lambda: db.get(models.Client, 1)

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            # Timed waits avoid lost selector wakeups in the sandbox's thread bridge.
            task = asyncio.create_task(http.get(f"/accounts/{account_id}/earmarks"))
            deadline = asyncio.get_running_loop().time() + 30
            while not task.done():
                await asyncio.wait({task}, timeout=0.01)
                if asyncio.get_running_loop().time() >= deadline:
                    task.cancel()
                    pytest.fail("Account earmarks request timed out")
            return task.result()

    return asyncio.run(request())


def test_each_capsules_claim_is_scoped_to_this_account(db):
    post(db, 900, [Leg(2, debit=300, capsule_id=1), Leg(2, debit=400, capsule_id=2),
                   Leg(3, debit=200, capsule_id=1), Leg(1, credit=900)])
    post(db, 50, [Leg(1, debit=50), Leg(2, credit=50, capsule_id=1)])
    post(db, 12345, [Leg(2, debit=12345, capsule_id=1), Leg(1, credit=12345)], "USD")
    response = get(db, 2)
    assert response.status_code == 200
    assert response.json() == [
        {"capsule_id": 1, "capsule_name": "Capsule 1", "claimed": 250,
         "claimed_minor": 250, "currency": "JPY", "max_share_bp": 2000},
        {"capsule_id": 2, "capsule_name": "Capsule 2", "claimed": 400,
         "claimed_minor": 400, "currency": "JPY", "max_share_bp": 4000},
        {"capsule_id": 3, "capsule_name": "Capsule 3", "claimed": 0,
         "claimed_minor": 0, "currency": "JPY", "max_share_bp": 0},
    ]


def test_account_without_sources_is_empty_even_with_old_journal_claim(db):
    post(db, 100, [Leg(3, debit=100, capsule_id=1), Leg(1, credit=100)])
    response = get(db, 3)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("account_id", [4, 999])
def test_foreign_or_missing_account_is_refused(db, account_id):
    response = get(db, account_id)
    assert response.status_code == 404
    assert response.json() == {"detail": "Account not found"}
    assert capsule_service.list_account_earmarks(db, 1, account_id) == []


def test_attached_capsule_without_claim_is_included(db):
    rows = get(db, 2).json()
    assert len(rows) == 3
    assert all(row["claimed"] == row["claimed_minor"] == 0 for row in rows)


def test_client_currency_fractional_claim_does_not_include_yen(db):
    db.get(models.Client, 1).general_settings = {"currency": "USD"}
    db.commit()
    post(db, 123, [Leg(2, debit=123, capsule_id=1), Leg(1, credit=123)], "USD")
    post(db, 500, [Leg(2, debit=500, capsule_id=1), Leg(1, credit=500)])
    source = db.get(models.Capsule, 1).funding_sources[0]
    source.max_share_bp = None
    db.commit()
    row = get(db, 2).json()[0]
    assert (row["claimed"], row["claimed_minor"], row["currency"], row["max_share_bp"]) == (1.23, 123, "USD", None)
