"""WP17 (R2): write-downs recorded, corrected and deleted from the ledger, linked like automatic ones."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import DomainError, Invalid, detail_for, status_for
from app.routers.depreciations import router as depreciations_router
from app.routers.transactions import router as transactions_router
from app.services import depreciation_service
from app.workflows import depreciation_workflow, ledger_entry_workflow


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(id=1, name="test", general_settings={"currency": "JPY"}))
    session.add(models.Client(id=2, name="other", general_settings={"currency": "JPY"}))
    session.add_all([
        models.Account(id=1, client_id=1, name="減価償却費", account_type="expense"),
        models.Account(id=2, client_id=1, name="備品", account_type="asset"),
        models.Account(id=3, client_id=1, name="雑費", account_type="expense"),
        models.Account(id=4, client_id=2, name="他人の費用", account_type="expense"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _product(db, **changes):
    values = dict(
        client_id=1, name="ノートPC", category="equipment", is_asset=True,
        last_unit_price_minor=240000, purchase_price_minor=240000,
        purchase_date=date(2026, 1, 1), lifespan_months=24,
        depreciation_method="straight_line", depreciation_interval="monthly",
        depreciation_start_date=date(2026, 1, 1),
    ) | changes
    product = models.Product(**values)
    db.add(product)
    db.commit()
    return product


def test_a_hand_recorded_write_down_follows_the_schedule_and_keeps_the_accounts(db):
    product = _product(db)
    preview = depreciation_workflow.preview(db, 1, product.id)
    assert (preview["next_period"], preview["due"], preview["expense_account_id"]) == ("2026-01", 10000, None)
    row = depreciation_workflow.record(db, 1, schemas.DepreciationRecord(
        product_id=product.id, period="2026-01", expense_account_id=1, asset_account_id=2))
    transaction = db.get(models.Transaction, row.transaction_id)
    assert transaction.date == date(2026, 1, 31) and transaction.amount_minor == 10000
    assert {(leg.account_id, leg.debit_minor, leg.credit_minor) for leg in transaction.journal_entries} == {(1, 10000, 0), (2, 0, 10000)}
    db.refresh(product)
    assert (product.depreciation_expense_account_id, product.depreciation_asset_account_id) == (1, 2)
    # The next write-down, by hand or automatic, moves on to the next period.
    assert depreciation_workflow.preview(db, 1, product.id)["next_period"] == "2026-02"
    with pytest.raises(Invalid):
        depreciation_workflow.record(db, 1, schemas.DepreciationRecord(product_id=product.id, period="2026-01"))


def test_a_write_down_may_name_its_amount_date_and_expense_but_not_more_than_the_book_value(db):
    product = _product(db, depreciation_expense_account_id=1, depreciation_asset_account_id=2)
    row = depreciation_workflow.record(db, 1, schemas.DepreciationRecord(
        product_id=product.id, period="2026-01", amount=12345, date=date(2026, 1, 15), expense_account_id=3))
    transaction = db.get(models.Transaction, row.transaction_id)
    assert (transaction.amount_minor, transaction.date) == (12345, date(2026, 1, 15))
    assert {leg.account_id for leg in transaction.journal_entries if leg.debit_minor} == {3}
    # The product keeps the expense account it already had.
    db.refresh(product)
    assert product.depreciation_expense_account_id == 1
    for bad in (dict(amount=240000), dict(expense_account_id=4), dict(expense_account_id=2)):
        with pytest.raises(Invalid):
            depreciation_workflow.record(db, 1, schemas.DepreciationRecord(product_id=product.id, period="2026-02", **bad))
    consumable = _product(db, name="洗剤", is_asset=False)
    with pytest.raises(Invalid):
        depreciation_workflow.record(db, 1, schemas.DepreciationRecord(product_id=consumable.id, period="2026-01", amount=100))


def test_correcting_or_editing_the_entry_keeps_the_record_and_deleting_it_restores_the_book_value(db):
    product = _product(db, depreciation_expense_account_id=1, depreciation_asset_account_id=2)
    row = depreciation_workflow.record(db, 1, schemas.DepreciationRecord(product_id=product.id, period="2026-01"))
    depreciation_workflow.amend(db, 1, row.id, schemas.DepreciationAmend(amount=8000, expense_account_id=3))
    transaction = db.get(models.Transaction, row.transaction_id)
    db.refresh(row)
    assert (row.amount_minor, transaction.amount_minor) == (8000, 8000)
    assert {(leg.account_id, leg.debit_minor) for leg in transaction.journal_entries if leg.debit_minor} == {(3, 8000)}
    with pytest.raises(Invalid):
        depreciation_workflow.amend(db, 1, row.id, schemas.DepreciationAmend(amount=240001))
    # A plain edit of the entry carries its amount to the record.
    ledger_entry_workflow.amend_entry(db, 1, transaction.id, schemas.TransactionUpdate(amount=7000))
    db.refresh(row)
    assert row.amount_minor == 7000
    assert depreciation_service.posted_minor(db, 1, product.id) == 7000
    ledger_entry_workflow.remove_entry(db, 1, transaction.id)
    assert depreciation_service.posted_minor(db, 1, product.id) == 0
    assert db.query(models.ProductDepreciation).count() == 0


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(depreciations_router)
    app.include_router(transactions_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    def domain_error(_request, exc):
        return JSONResponse(status_code=status_for(exc), content={"detail": detail_for(exc)})

    return TestClient(app)


def test_http_preview_record_amend_and_the_ledger_marks_the_entry(db, api):
    product = _product(db, depreciation_expense_account_id=1, depreciation_asset_account_id=2)
    assert api.get("/depreciations/preview", params={"product_id": product.id}).json()["due"] == 10000
    created = api.post("/depreciations", json={"product_id": product.id, "period": "2026-01"})
    assert created.status_code == 200, created.text
    record = created.json()
    listed = api.get("/transactions/", params={"start_date": "2026-01-01", "end_date": "2026-01-31"}).json()
    assert listed[0]["depreciation"] == {"id": record["id"], "product_id": product.id, "product_name": "ノートPC", "period": "2026-01"}
    assert api.put(f"/depreciations/{record['id']}", json={"amount": 9000}).status_code == 200
    assert api.post("/depreciations", json={"product_id": product.id, "period": "2026-01"}).status_code == 400
    assert api.put("/depreciations/999", json={"amount": 1}).status_code == 400
