"""Writing an asset down has to agree with the journal that carries it.

The direct method is used, so the expense is debited and the item account
credited and the asset's carrying amount falls. The book value is never stored:
it is the purchase price less the postings, which is what keeps the figure and
the entries from drifting apart.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.domain.errors import Invalid
from app.services import depreciation_service


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(id=1, name="test", general_settings={"currency": "JPY"}))
    session.add_all([
        models.Account(id=1, client_id=1, name="depreciation", account_type="expense"),
        models.Account(id=2, client_id=1, name="equipment", account_type="asset"),
        models.Account(id=3, client_id=1, name="other client", account_type="expense"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _product(db, **changes):
    values = dict(
        client_id=1, name="laptop", category="equipment", is_asset=True,
        last_unit_price_minor=240000, purchase_price_minor=240000,
        purchase_date=date(2026, 1, 1), lifespan_months=24,
        depreciation_method="straight_line", depreciation_interval="monthly",
        depreciation_start_date=date(2026, 1, 1),
        depreciation_expense_account_id=1, depreciation_asset_account_id=2,
    ) | changes
    product = models.Product(**values)
    db.add(product)
    db.commit()
    return product


def _post_all(db, product, periods):
    for period in periods:
        depreciation_service._post(db, 1, product.id, period=period)


def _periods(count, year=2026, month=1):
    out = []
    for index in range(count):
        total = month - 1 + index
        out.append(f"{year + total // 12}-{total % 12 + 1:02d}")
    return out


def test_straight_line_over_a_full_life_sums_to_the_purchase_price(db):
    product = _product(db)
    _post_all(db, product, _periods(24))
    assert depreciation_service.posted_minor(db, 1, product.id) == 240000
    assert depreciation_service.schedule(db, 1, product.id)["book_value_minor"] == 0


def test_the_last_posting_takes_whatever_is_left(db):
    """A price that does not divide evenly must still land exactly on zero."""
    product = _product(db, purchase_price_minor=100000, lifespan_months=3)
    _post_all(db, product, _periods(3))
    amounts = [row.amount_minor for row in _postings(db, 1, product.id)]
    assert sum(amounts) == 100000
    assert depreciation_service.schedule(db, 1, product.id)["book_value_minor"] == 0


def test_the_entry_is_debit_expense_credit_item(db):
    product = _product(db)
    transaction, row = depreciation_service._post(db, 1, product.id, period="2026-01")
    legs = {leg.account_id: (leg.debit_minor, leg.credit_minor) for leg in transaction.journal_entries}
    assert legs == {1: (row.amount_minor, 0), 2: (0, row.amount_minor)}
    assert transaction.amount_minor == row.amount_minor
    # Posted at the end of the period it belongs to, not on the day it was run.
    assert transaction.date == date(2026, 1, 31)


def test_declining_balance_falls_and_terminates(db):
    product = _product(
        db, depreciation_method="declining_balance", depreciation_annual_rate=60.0,
        lifespan_months=36,
    )
    amounts = []
    for period in _periods(36):
        schedule = depreciation_service.schedule(db, 1, product.id)
        if schedule["book_value_minor"] == 0:
            break
        depreciation_service._post(db, 1, product.id, period=period)
        amounts.append(_postings(db, 1, product.id)[0].amount_minor)
    # Falling, except the last: the end of the useful life takes the remainder,
    # which is a catch-up and is larger than the instalment before it.
    assert amounts[:-1] == sorted(amounts[:-1], reverse=True)
    assert amounts[-1] >= amounts[-2]
    assert sum(amounts) == 240000
    assert depreciation_service.schedule(db, 1, product.id)["book_value_minor"] == 0


def test_a_period_cannot_be_posted_twice(db):
    product = _product(db)
    depreciation_service._post(db, 1, product.id, period="2026-01")
    with pytest.raises(Invalid) as error:
        depreciation_service._post(db, 1, product.id, period="2026-01")
    assert "2026-01" in str(error.value)
    assert len(_postings(db, 1, product.id)) == 1


def test_a_period_before_the_start_is_refused(db):
    product = _product(db)
    with pytest.raises(Invalid) as error:
        depreciation_service._post(db, 1, product.id, period="2025-12")
    assert "2026-01" in str(error.value)


@pytest.mark.parametrize("missing", ["depreciation_expense_account_id", "depreciation_asset_account_id"])
def test_both_accounts_are_required_and_named(db, missing):
    product = _product(db, **{missing: None})
    with pytest.raises(Invalid) as error:
        depreciation_service._post(db, 1, product.id, period="2026-01")
    assert "account" in str(error.value)


def test_a_product_without_a_method_is_refused(db):
    product = _product(db, depreciation_method="none")
    with pytest.raises(Invalid):
        depreciation_service._post(db, 1, product.id, period="2026-01")
    assert depreciation_service.schedule(db, 1, product.id)["blocked_reason"]


def test_another_clients_product_is_not_found(db):
    product = _product(db)
    with pytest.raises(Invalid):
        depreciation_service._post(db, 2, product.id, period="2026-01")


def test_deleting_the_entry_removes_the_posting(db):
    product = _product(db)
    transaction, _ = depreciation_service._post(db, 1, product.id, period="2026-01")
    db.query(models.JournalEntry).filter_by(transaction_id=transaction.id).delete()
    db.delete(db.get(models.Transaction, transaction.id))
    db.commit()
    assert _postings(db, 1, product.id) == []
    # And the schedule offers the period again, because nothing carried it.
    assert depreciation_service.schedule(db, 1, product.id)["next_period"] == "2026-01"


def test_a_yearly_interval_posts_twelve_months_and_steps_a_year(db):
    product = _product(db, depreciation_interval="yearly")
    depreciation_service._post(db, 1, product.id, period="2026-01")
    assert depreciation_service.posted_minor(db, 1, product.id) == 120000
    assert depreciation_service.schedule(db, 1, product.id)["next_period"] == "2027-01"



def _postings(db, client_id, product_id):
    return db.query(models.ProductDepreciation).filter_by(client_id=client_id, product_id=product_id).order_by(models.ProductDepreciation.period.desc()).all()
