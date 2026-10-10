from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models, schemas
    from backend.app.database import Base
    from backend.app.routers.recurring import create_recurring_transaction, update_recurring_transaction, patch_recurring_transaction
    from backend.app.services import registry_service
    from backend.app.services.action_bridge_service import apply_action
    from backend.app.services.periods import add_months, current_period_key
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models, schemas  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers.recurring import create_recurring_transaction, update_recurring_transaction, patch_recurring_transaction  # type: ignore[no-redef]
    from app.services import registry_service  # type: ignore[no-redef]
    from app.services.action_bridge_service import apply_action  # type: ignore[no-redef]
    from app.services.periods import add_months, current_period_key  # type: ignore[no-redef]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
    session.add_all([
        models.Account(client_id=1, name="bank", account_type="asset", balance=100000),
        models.Account(client_id=1, name="subscriptions", account_type="expense", balance=0),
        models.Account(client_id=1, name="savings", account_type="asset", balance=0),
    ])
    session.flush()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _payload(db, **changes):
    accounts = {row.name: row for row in db.query(models.Account).all()}
    return dict(name="subscription", amount=1200, frequency="Monthly",
                from_account_id=accounts["bank"].id, to_account_id=accounts["subscriptions"].id) | changes


def _create(db, **changes):
    return create_recurring_transaction(
        schemas.RecurringTransactionCreate(**_payload(db, **changes)), db, db.get(models.Client, 1)
    )


def _assert_link(db, recurring):
    entry = db.query(models.RegistryEntry).one()
    assert db.query(models.RecurringTransaction).count() == 1
    assert entry.source_recurring_transaction_id == recurring.id
    assert recurring.source_registry_entry_id == entry.id
    assert entry.generate_recurring is True
    assert entry.budget_active is True
    return entry


def test_router_create_has_one_registry_and_symmetric_link(db):
    recurring = _create(db)
    entry = _assert_link(db, recurring)
    assert (entry.line_type, entry.entry_type) == ("expense", "service")
    assert (entry.name, entry.amount, entry.currency) == ("subscription", 1200, "JPY")


def test_router_update_and_patch_keep_one_to_one_link(db):
    recurring = _create(db, is_active=False)
    entry_id = recurring.source_registry_entry_id
    recurring = update_recurring_transaction(
        recurring.id, schemas.RecurringTransactionCreate(**_payload(
            db, name="updated", amount=2500, day_of_month=14, is_active=False)),
        db, db.get(models.Client, 1),
    )
    entry = _assert_link(db, recurring)
    assert entry.id == entry_id
    assert (entry.name, entry.amount, entry.day_of_month) == ("updated", 2500, 14)
    entry.budget_active = False
    recurring = patch_recurring_transaction(
        recurring.id, schemas.RecurringTransactionUpdate(amount=3000), db, db.get(models.Client, 1)
    )
    entry = _assert_link(db, recurring)
    assert (entry.name, entry.amount, entry.day_of_month, entry.is_active) == ("updated", 3000, 14, False)


def test_registry_sync_is_idempotent(db):
    recurring = registry_service.upsert_registry_from_recurring_payload(db, 1, _payload(db))
    entry = _assert_link(db, recurring)
    before = {column.name: getattr(recurring, column.name) for column in recurring.__table__.columns}
    registry_service.sync_recurring_from_registry(db, entry)
    db.flush()
    assert before == {column.name: getattr(recurring, column.name) for column in recurring.__table__.columns}


def test_accounts_decide_expense_and_allocation_shape(db):
    recurring = _create(db)
    entry = _assert_link(db, recurring)
    assert entry.budget_account_id == recurring.to_account_id
    savings = db.query(models.Account).filter_by(name="savings").one()
    recurring = patch_recurring_transaction(
        recurring.id, schemas.RecurringTransactionUpdate(to_account_id=savings.id), db, db.get(models.Client, 1)
    )
    entry = _assert_link(db, recurring)
    assert (entry.line_type, entry.entry_type, entry.budget_account_id) == ("allocation", "allocation", None)


def test_end_period_prevents_revival_and_future_stays_active(db):
    recurring = _create(db, end_period=add_months(current_period_key(), -1))
    entry = _assert_link(db, recurring)
    assert entry.is_active is True
    assert recurring.is_active is False
    registry_service.sync_recurring_from_registry(db, entry)
    assert recurring.is_active is False
    entry.end_period = add_months(current_period_key(), 1)
    registry_service.sync_recurring_from_registry(db, entry)
    assert recurring.is_active is True
    entry.end_period = current_period_key()
    registry_service.sync_recurring_from_registry(db, entry)
    assert recurring.is_active is True


def test_apply_add_recurring_creates_link_and_next_due_date(db):
    action = models.MonthlyAction(
        client_id=1, source_period="2026-09", target_period="2026-10",
        proposal_id="add-recurring-1", idempotency_key="add-recurring-1",
        kind="add_recurring", status="pending", payload=_payload(db, day_of_month=14),
    )
    db.add(action)
    db.commit()
    result = apply_action(db, 1, action.id)
    recurring = db.query(models.RecurringTransaction).one()
    _assert_link(db, recurring)
    assert result["result"]["recurring_id"] == recurring.id
    assert recurring.next_due_date is not None


def test_reverse_sync_is_absent():
    assert not hasattr(registry_service, "sync_registry_from_recurring")


def test_router_create_preserves_manual_approval(db):
    recurring = _create(db, auto_post=False)
    assert recurring.auto_post is False
    entry = _assert_link(db, recurring)
    assert entry.generate_recurring is True
    recurring = patch_recurring_transaction(
        recurring.id, schemas.RecurringTransactionUpdate(amount=1500), db, db.get(models.Client, 1)
    )
    assert recurring.auto_post is False


def test_router_update_preserves_explicit_next_due_date(db):
    recurring = _create(db)
    due = date(2030, 3, 19)
    recurring = update_recurring_transaction(
        recurring.id,
        schemas.RecurringTransactionCreate(**_payload(db, day_of_month=14, next_due_date=due)),
        db, db.get(models.Client, 1),
    )
    assert recurring.next_due_date == due
    _assert_link(db, recurring)
