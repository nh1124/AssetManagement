from app.services.ledger_valuation import calculate_account_valued_balance
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.domain.errors import Invalid
from backend.app.services import ledger_service as ledger
from backend.app.workflows.ledger_entry_workflow import record_entry


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add_all([
        models.Client(id=1, name="account-tree", general_settings={}),
        models.Client(id=2, name="other", general_settings={}),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _account(db, name="parent", account_type="asset", client_id=1, **data):
    return ledger.create_account(db, client_id, dict(name=name, account_type=account_type, **data))


def _refusal(category, detail, operation):
    with pytest.raises(category) as exc:
        operation()
    assert str(exc.value) == detail


def test_delete_deactivates_only_the_account_and_preserves_all_history(db):
    cash = _account(db, name="cash")
    food = _account(db, name="food", account_type="expense")
    transaction = record_entry(db, 1, schemas.TransactionCreate(
        date=date(2026, 10, 11), description="lunch", amount=300,
        from_account_id=cash.id, to_account_id=food.id,
    ))
    before = [(leg.id, leg.transaction_id, leg.account_id, leg.debit, leg.credit)
              for leg in db.query(models.JournalEntry).order_by(models.JournalEntry.id)]
    balance = calculate_account_valued_balance(db, cash)
    assert ledger.delete_account(db, 1, cash.id) is True
    db.refresh(cash)
    assert cash.is_active is False
    assert calculate_account_valued_balance(db, cash) == balance == -300
    assert db.query(models.Transaction).one().id == transaction.id
    assert [(leg.id, leg.transaction_id, leg.account_id, leg.debit, leg.credit)
            for leg in db.query(models.JournalEntry).order_by(models.JournalEntry.id)] == before
    assert db.get(models.Account, cash.id) is cash
    assert ledger.delete_account(db, 1, cash.id) is True


@pytest.mark.parametrize("missing", ["unknown", "other_client"])
def test_update_and_delete_return_missing_without_modifying_other_clients(db, missing):
    account = _account(db, client_id=2)
    account_id = 999999 if missing == "unknown" else account.id
    assert ledger.update_account(db, 1, account_id, {"name": "changed"}) is None
    assert ledger.delete_account(db, 1, account_id) is False
    assert account.name == "parent"
    assert account.is_active is True


@pytest.mark.parametrize("field,value,detail", [
    ("liability_closing_day", 0, "liability_closing_day must be between 1 and 31"),
    ("liability_payment_day", 32, "liability_payment_day must be between 1 and 31"),
    ("liability_payment_month_offset", -1, "liability_payment_month_offset must be between 0 and 24"),
    ("liability_payment_month_offset", 25, "liability_payment_month_offset must be between 0 and 24"),
    ("liability_installment_months", 0, "liability_installment_months must be positive"),
    ("liability_minimum_payment", -1, "liability_minimum_payment must not be negative"),
    ("liability_fixed_payment_amount", -1, "liability_fixed_payment_amount must not be negative"),
    ("liability_revolving_rate", -1, "liability_revolving_rate must not be negative"),
])
def test_liability_settings_preserve_each_range_refusal(db, field, value, detail):
    _refusal(Invalid, detail, lambda: _account(db, account_type="liability", **{field: value}))


def test_liability_update_preserves_omitted_settings_and_nonliability_strips_settings(db):
    liability = _account(db, account_type="liability", liability_payment_policy="fixed",
                         liability_payment_month_offset=2, liability_closing_day=31)
    ledger.update_account(db, 1, liability.id, {"name": "renamed"})
    assert (liability.liability_payment_policy, liability.liability_payment_month_offset) == ("fixed", 2)
    ledger.update_account(db, 1, liability.id, {"liability_payment_policy": None, "liability_payment_month_offset": None})
    assert (liability.liability_payment_policy, liability.liability_payment_month_offset) == ("full", 0)
    assert liability.liability_closing_day == 31
    asset = _account(db, name="asset", liability_closing_day=-10)
    assert asset.liability_closing_day is None
    ledger.update_account(db, 1, asset.id, {"liability_closing_day": 32})
    assert asset.liability_closing_day is None


def test_opening_balance_tolerance_and_update_balance_refusal_are_preserved(db):
    account = _account(db, balance=0.01)
    assert calculate_account_valued_balance(db, account) == 0
    _refusal(Invalid, "Journal is the source of truth. Create an opening-balance transaction instead of setting account.balance.",
             lambda: _account(db, name="invalid", balance=0.02))
    _refusal(Invalid, "Journal is the source of truth. Use transactions to change balances.",
             lambda: ledger.update_account(db, 1, account.id, {"balance": None}))


def test_account_crud_commit_false_leaves_changes_for_the_caller(db):
    existing = _account(db)
    account = ledger.create_account(db, 1, {"name": "pending", "account_type": "asset"}, commit=False)
    ledger.update_account(db, 1, existing.id, {"name": "changed"}, commit=False)
    assert ledger.delete_account(db, 1, existing.id, commit=False) is True
    pending_id = account.id
    db.rollback()
    assert db.get(models.Account, pending_id) is None
    assert existing.name == "parent"
    assert existing.is_active is True
