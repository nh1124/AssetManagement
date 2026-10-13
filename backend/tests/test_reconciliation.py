"""Statement comparisons and corrections are journal facts, scoped by owner/date/currency."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, Invalid, NotFound, detail_for, status_for
from app.domain.journal import Leg
from app.routers import analysis
from app.services import capsule_service, ledger_service, reconciliation_service as reconcile

DAY = date(2026, 10, 14)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add_all([models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"}) for i in [1, 2]])
        session.flush()
        session.add_all([
            models.Account(id=1, client_id=1, name="Bank", account_type="asset"),
            models.Account(id=2, client_id=1, name="Correction", account_type="expense"),
            models.Account(id=3, client_id=1, name="Other bank", account_type="asset"),
            models.Account(id=4, client_id=2, name="Foreign bank", account_type="asset"),
            models.Account(id=5, client_id=1, name="Card", account_type="liability"),
            models.Capsule(id=1, client_id=1, name="Reserve", target_amount_minor=1000),
            models.Capsule(id=2, client_id=2, name="Foreign reserve", target_amount_minor=1000),
            models.Capsule(id=3, client_id=1, name="Empty reserve", target_amount_minor=1000),
        ])
        session.commit()
        yield session
    engine.dispose()


def post(db, amount=1000, *, day=DAY, currency="JPY", capsule_id=None, target=1, source=2):
    transaction = ledger_service.create_transaction(
        db, client_id=1, date=day, description="Journal fact", amount_minor=amount, currency=currency,
        legs=[Leg(target, debit=amount, capsule_id=capsule_id), Leg(source, credit=amount)],
    )
    db.commit()
    return transaction


def compare(db, statement=1100, **kwargs):
    return reconcile.compare_to_statement(db, 1, 1, as_of=DAY, statement_minor=statement, **kwargs)


def adjust(db, statement=1100, **kwargs):
    return reconcile.post_adjustment(db, 1, 1, as_of=DAY, statement_minor=statement, counter_account_id=2, **kwargs)


def test_difference_reads_journal_legs_not_transaction_total_and_ignores_future(db):
    ledger_service.create_transaction(db, client_id=1, date=DAY, description="Compound", amount_minor=1000, currency="JPY",
                                      legs=[Leg(1, debit=600), Leg(3, debit=400), Leg(2, credit=1000)])
    db.commit()
    post(db, 2000, day=DAY + timedelta(days=1))
    assert compare(db, 625) == {
        "account": {"id": 1, "name": "Bank", "account_type": "asset"}, "as_of": DAY,
        "ledger_minor": 600, "statement_minor": 625, "difference_minor": 25,
        "currency": "JPY", "capsule_claims": [],
    }


@pytest.mark.parametrize("statement", [1250, 750, -50])
def test_adjustment_closes_the_difference_exactly_in_both_directions(db, statement):
    post(db)
    tx = adjust(db, statement, note="Verified statement")
    assert tx.date == DAY and tx.amount_minor == abs(statement - 1000) and tx.description == "Verified statement"
    entries = {row.account_id: row for row in tx.journal_entries}
    assert entries[1].debit_minor - entries[1].credit_minor == statement - 1000
    assert entries[2].debit_minor - entries[2].credit_minor == 1000 - statement
    assert compare(db, statement)["difference_minor"] == 0
    assert db.query(models.Transaction).count() == 2


def test_zero_difference_refused_without_writes(db):
    post(db)
    with pytest.raises(Invalid, match="zero difference"):
        adjust(db, 1000)
    assert db.query(models.Transaction).count() == 1
    assert db.query(models.JournalEntry).count() == 2


@pytest.mark.parametrize("statement", [1250, 750])
def test_capsule_attribution_is_only_on_reconciled_leg_and_claim_moves(db, statement):
    post(db, capsule_id=1)
    tx = adjust(db, statement, capsule_id=1)
    assert {row.account_id: row.capsule_id for row in tx.journal_entries} == {1: 1, 2: None}
    assert capsule_service.claimed_minor(db, 1, 1, account_id=1) == {"JPY": statement}
    assert compare(db, statement)["capsule_claims"] == [{"capsule_id": 1, "capsule_name": "Reserve", "claimed_minor": statement}]


def test_no_capsule_leaves_existing_claim_unchanged(db):
    post(db, capsule_id=1)
    tx = adjust(db, 500)
    assert all(row.capsule_id is None for row in tx.journal_entries)
    assert capsule_service.claimed_minor(db, 1, 1) == {"JPY": 1000}


def test_claims_have_same_account_cutoff_and_currency_as_comparison(db):
    post(db, 700, capsule_id=1)
    post(db, 200, capsule_id=1, target=3)
    post(db, 500, capsule_id=1, currency="USD")
    post(db, 300, capsule_id=1, day=DAY + timedelta(days=1))
    ledger_service.propose_transaction(db, 1, origin="capsule", date=DAY, description="Unposted", amount_minor=100,
                                      currency="JPY", legs=[Leg(1, debit=100, capsule_id=1), Leg(2, credit=100)])
    db.commit()
    assert compare(db, 700)["capsule_claims"] == [{"capsule_id": 1, "capsule_name": "Reserve", "claimed_minor": 700}]
    result = compare(db, 500, currency="USD")
    assert result["ledger_minor"] == 500 and result["difference_minor"] == 0
    assert result["capsule_claims"][0]["claimed_minor"] == 500


def test_currency_minor_units_are_never_added_together(db):
    post(db, 1000)
    post(db, 1234, currency="USD", capsule_id=1)
    assert compare(db, 1000)["ledger_minor"] == 1000
    tx = adjust(db, 1250, currency="USD", capsule_id=1)
    assert tx.amount_minor == 16 and tx.currency == "USD"
    assert compare(db, 1250, currency="USD")["difference_minor"] == 0
    assert capsule_service.claimed_minor(db, 1, 1) == {"USD": 1250}


@pytest.mark.parametrize("patch", [{"account_id": 4}, {"counter_account_id": 4}, {"capsule_id": 2}, {"account_id": 999}])
def test_foreign_or_missing_references_refused_before_posting(db, patch):
    with pytest.raises(NotFound):
        reconcile.post_adjustment(db, 1, **{"account_id": 1, "counter_account_id": 2, "as_of": DAY, "statement_minor": 100, **patch})
    assert db.query(models.Transaction).count() == 0


def test_same_counter_account_refused(db):
    with pytest.raises(Invalid, match="must differ"):
        reconcile.post_adjustment(db, 1, 1, as_of=DAY, statement_minor=100, counter_account_id=1)
    assert db.query(models.Transaction).count() == 0


def test_changed_balance_requires_new_confirmation(db):
    post(db)
    with pytest.raises(Conflict, match="changed"):
        adjust(db, 1100, expected_ledger_minor=900)
    assert db.query(models.Transaction).count() == 1


def test_commit_false_leaves_transaction_under_callers_control(db):
    post(db)
    tx = adjust(db, 1100, commit=False)
    assert db.get(models.Transaction, tx.id) is not None
    assert compare(db, 1100)["difference_minor"] == 0
    db.rollback()
    assert compare(db, 1100)["difference_minor"] == 100


def test_credit_balance_uses_debit_net_to_follow_requested_posting_direction(db):
    post(db, 1000, target=2, source=5)
    tx = reconcile.post_adjustment(db, 1, 5, as_of=DAY, statement_minor=-750, counter_account_id=2)
    assert next(row for row in tx.journal_entries if row.account_id == 5).debit_minor == 250
    assert reconcile.compare_to_statement(db, 1, 5, as_of=DAY, statement_minor=-750)["difference_minor"] == 0


@pytest.fixture
def http(db):
    app = FastAPI()
    app.include_router(analysis.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_request, exc):
        return JSONResponse(status_code=status_for(exc), content={"detail": detail_for(exc)})

    with TestClient(app) as client:
        yield client


def test_http_contract_and_adjusted_entry_serialization(db, http):
    post(db, 1234, currency="USD", capsule_id=1)
    query = {"as_of": DAY.isoformat(), "statement": "12.50", "currency": "USD"}
    comparison = http.get("/analysis/reconcile/1", params=query)
    assert comparison.status_code == 200
    assert comparison.json()["difference_minor"] == 16
    response = http.post("/analysis/reconcile/1/adjust", json={**query, "counter_account_id": 2, "capsule_id": 1, "expected_ledger_minor": 1234})
    assert response.status_code == 200
    assert response.json()["amount"] == 0.16
    assert response.json()["legs"][0]["capsule_id"] == 1
    assert http.get("/analysis/reconcile/1", params=query).json()["difference_minor"] == 0
    assert http.post("/analysis/reconcile/1/adjust", json={**query, "counter_account_id": 2}).status_code == 400


def test_old_stub_routes_are_gone(http):
    assert http.get("/analysis/reconcile").status_code == 404
    # The new GET path matches "fix" as a path segment, but has no POST method.
    assert http.post("/analysis/reconcile/fix").status_code == 405


@pytest.mark.parametrize("statement", ["NaN", "Infinity", "-Infinity", "invalid"])
def test_http_refuses_nonfinite_or_invalid_statement(http, statement):
    assert http.get("/analysis/reconcile/1", params={"as_of": str(DAY), "statement": statement}).status_code == 422
    assert http.post("/analysis/reconcile/1/adjust", json={"as_of": str(DAY), "statement": statement, "counter_account_id": 2}).status_code == 422


def test_unsupported_currency_is_a_domain_refusal(http):
    assert http.get("/analysis/reconcile/1", params={"as_of": str(DAY), "statement": "10", "currency": "XYZ"}).status_code == 400


def test_statement_major_input_uses_exact_decimal_minor_units(db):
    assert reconcile.statement_money(db, 1, Decimal("12.34"), "USD").minor == 1234
