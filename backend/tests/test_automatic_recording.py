"""Every automatic recording is set in the registry and run in one place (WP7, U4).

A generated definition posts on its due date unless it waits for a hand; a
product's definition can write its asset down each ended period. Both are
switched on the registry entry, and one workflow runs them.
"""
from __future__ import annotations

from datetime import date

import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.domain.errors import Invalid
from app.services import depreciation_service, recurring_service, registry_service
from app.workflows import automatic_recording_workflow as workflow

TODAY = date(2026, 4, 15)


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
        models.Account(id=2, client_id=1, name="equipment", account_type="item"),
        models.Account(id=3, client_id=1, name="bank", account_type="asset"),
        models.Account(id=4, client_id=1, name="subscriptions", account_type="expense"),
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


def _definition(db, **changes):
    data = dict(
        name="subscription", entry_type="service", amount=1200, frequency="Monthly", day_of_month=1,
        line_type="expense", source_account_id=3, destination_account_id=4, generate_recurring=True,
    ) | changes
    entry = registry_service.create_entry(db, 1, data)
    recurring = db.get(models.RecurringTransaction, entry.source_recurring_transaction_id)
    recurring.next_due_date = date(2026, 4, 1)
    db.commit()
    return entry, recurring


def _postings(db, product):
    return [row.period for row in depreciation_service.list_postings(db, 1, product.id)]


def test_switching_on_writes_down_every_ended_period_and_no_more(db):
    product = _product(db)
    assert depreciation_service.pending_periods(db, 1, product, TODAY) == 3

    result = workflow.set_auto_depreciation(db, 1, product.id, enabled=True, today=TODAY)

    assert result["posted_periods"] == ["2026-01", "2026-02", "2026-03"]
    # April has not ended, so it is not written down ahead of the calendar.
    assert sorted(_postings(db, product)) == ["2026-01", "2026-02", "2026-03"]
    entry = registry_service.get_product_entry(db, 1, product.id)
    assert entry.auto_depreciation is True and entry.entry_type == "asset"
    assert depreciation_service.pending_periods(db, 1, product, TODAY) == 0


def test_the_daily_run_posts_both_kinds_and_leaves_manual_definitions_waiting(db):
    product = _product(db)
    workflow.set_auto_depreciation(db, 1, product.id, enabled=True, today=date(2026, 1, 15))
    _, automatic = _definition(db)
    _, manual = _definition(db, name="rent", auto_post=False)

    workflow.process_due_all(db, today=TODAY)

    assert sorted(_postings(db, product)) == ["2026-01", "2026-02", "2026-03"]
    assert db.query(models.Transaction).filter_by(recurring_transaction_id=automatic.id).count() == 1
    assert db.query(models.Transaction).filter_by(recurring_transaction_id=manual.id).count() == 0
    db.refresh(manual)
    assert manual.auto_post is False and manual.next_due_date == date(2026, 4, 1)


def test_switching_off_stops_the_write_down(db):
    product = _product(db)
    workflow.set_auto_depreciation(db, 1, product.id, enabled=True, today=date(2026, 1, 15))
    workflow.set_auto_depreciation(db, 1, product.id, enabled=False)

    workflow.process_due(db, 1, today=TODAY)

    assert _postings(db, product) == []
    assert registry_service.clients_with_auto_depreciation(db) == set()


def test_catch_up_is_bounded_per_run(db):
    product = _product(db, purchase_date=date(2023, 1, 1), depreciation_start_date=date(2023, 1, 1), lifespan_months=60)
    result = workflow.set_auto_depreciation(db, 1, product.id, enabled=True, today=TODAY)
    assert len(result["posted_periods"]) == depreciation_service.CATCH_UP_LIMIT
    workflow.process_due(db, 1, today=TODAY)
    assert len(_postings(db, product)) == 39  # 2023-01 .. 2026-03


def test_a_product_that_cannot_be_written_down_is_refused(db):
    product = _product(db, depreciation_expense_account_id=None)
    with pytest.raises(Invalid, match="勘定科目"):
        workflow.set_auto_depreciation(db, 1, product.id, enabled=True, today=TODAY)
    assert registry_service.get_product_entry(db, 1, product.id) is None
    consumable = _product(db, name="paper", is_asset=False)
    with pytest.raises(Invalid, match="固定資産"):
        workflow.set_auto_depreciation(db, 1, consumable.id, enabled=True, today=TODAY)


def test_a_definition_save_without_the_settings_keeps_them(db):
    entry, recurring = _definition(db, auto_post=False)
    data = {key: getattr(entry, key) for key in (
        "name", "entry_type", "frequency", "day_of_month", "line_type",
        "source_account_id", "destination_account_id", "generate_recurring",
    )} | {"amount": 1500, "auto_post": None, "auto_depreciation": None}

    registry_service.update_entry(db, 1, entry.id, data)

    db.refresh(recurring)
    assert entry.auto_post is False and recurring.auto_post is False
    registry_service.update_entry(db, 1, entry.id, data | {"auto_post": True})
    db.refresh(recurring)
    assert recurring.auto_post is True


def test_only_a_product_definition_can_write_down(db):
    entry, _ = _definition(db, auto_depreciation=True)
    assert entry.auto_depreciation is False


def test_the_definition_follows_product_edits_and_deletion_switches_it_off(db):
    product = _product(db)
    workflow.set_auto_depreciation(db, 1, product.id, enabled=True, today=date(2026, 1, 15))
    product.name = "laptop 2"
    registry_service.refresh_product_entry(db, product)
    entry = registry_service.get_product_entry(db, 1, product.id)
    assert entry.name == "laptop 2" and entry.auto_depreciation is True

    registry_service.detach_product(db, entry, commit=True)
    assert entry.auto_depreciation is False and entry.source_product_id is None


def test_a_month_lists_its_automatic_transactions_by_account(db):
    product = _product(db)
    workflow.set_auto_depreciation(db, 1, product.id, enabled=True, today=date(2026, 4, 1))
    _definition(db, day_of_month=31)
    _definition(db, name="rent", auto_post=False, day_of_month=10)
    registry_service.create_entry(db, 1, dict(
        name="plan only", entry_type="service", amount=500, frequency="Monthly", day_of_month=5,
        line_type="expense", source_account_id=3, destination_account_id=4, generate_recurring=False,
    ))
    _definition(db, name="yearly", frequency="Yearly", month_of_year=7, day_of_month=1)
    before = (db.query(models.Transaction).count(), db.query(models.ProductDepreciation).count())

    april = workflow.scheduled_in_period(db, 1, "2026-04")["items"]

    assert (db.query(models.Transaction).count(), db.query(models.ProductDepreciation).count()) == before
    by_name = {item["name"]: item for item in april}
    assert set(by_name) == {"subscription", "rent", "plan only", "laptop"}
    # The day is clamped to the month, and next_due_date (2026-04-01) is not past it.
    assert by_name["subscription"]["date"] == date(2026, 4, 30)
    assert by_name["subscription"]["recording"] == "auto" and by_name["subscription"]["posted"] is False
    assert by_name["rent"]["recording"] == "manual"
    assert by_name["plan only"]["recording"] == "none" and by_name["plan only"]["posted"] is None
    assert (by_name["rent"]["account_id"], by_name["rent"]["counter_account_id"]) == (4, 3)
    laptop = by_name["laptop"]
    assert (laptop["kind"], laptop["amount"], laptop["recording"], laptop["posted"]) == ("depreciation", 10000, "auto", False)
    assert (laptop["account_id"], laptop["counter_account_id"]) == (1, 2)
    march = {item["name"]: item for item in workflow.scheduled_in_period(db, 1, "2026-03")["items"]}
    assert march["laptop"]["posted"] is True and march["subscription"]["posted"] is True
    assert "yearly" in {item["name"] for item in workflow.scheduled_in_period(db, 1, "2026-07")["items"]}
    # After the useful life nothing is written down.
    assert all(item["kind"] != "depreciation" for item in workflow.scheduled_in_period(db, 1, "2028-01")["items"])
    with pytest.raises(Invalid):
        workflow.scheduled_in_period(db, 1, "April")


def test_the_list_shows_what_runs_and_writes_nothing(db):
    product = _product(db)
    _definition(db, auto_post=False)
    before = (db.query(models.RegistryEntry).count(), db.query(models.Transaction).count())

    listing = workflow.list_recordings(db, 1, today=TODAY)

    assert (db.query(models.RegistryEntry).count(), db.query(models.Transaction).count()) == before
    [recurring] = listing["recurring"]
    assert recurring["auto_post"] is False and recurring["is_due"] is True
    [depreciation] = listing["depreciation"]
    assert depreciation["product_id"] == product.id
    assert depreciation["auto_depreciation"] is False and depreciation["entry_id"] is None
    assert depreciation["pending_periods"] == 3 and depreciation["blocked_reason"] is None


def test_a_write_down_by_hand_posts_the_ended_periods_once(db):
    product = _product(db)

    result = workflow.post_due_depreciation(db, 1, product.id, today=TODAY)

    assert result["posted_periods"] == ["2026-01", "2026-02", "2026-03"]
    assert registry_service.get_product_entry(db, 1, product.id) is None  # by hand needs no definition
    with pytest.raises(Invalid, match="まだありません"):
        workflow.post_due_depreciation(db, 1, product.id, today=TODAY)
    assert _postings(db, product) == ["2026-03", "2026-02", "2026-01"]


def test_a_write_down_by_hand_is_refused_when_it_cannot_post(db):
    product = _product(db, depreciation_asset_account_id=None)
    with pytest.raises(Invalid, match="勘定科目"):
        workflow.post_due_depreciation(db, 1, product.id, today=TODAY)
    consumable = _product(db, name="paper", is_asset=False)
    with pytest.raises(Invalid, match="固定資産"):
        workflow.post_due_depreciation(db, 1, consumable.id, today=TODAY)
    assert db.query(models.Transaction).count() == 0


# --- 記帳待ち in the inbox (U18) -------------------------------------------------

def _recording_due(db):
    from app.workflows import notification_workflow

    return notification_workflow.recording_due_notifications(db, 1, date.today().strftime("%Y-%m"))


def _due_definition(db, **changes):
    entry, recurring = _definition(db, **changes)
    recurring.next_due_date = date.today() - relativedelta(days=1)
    db.commit()
    return entry, recurring


def test_waiting_items_whose_date_has_come_are_notified_by_tab(db):
    _due_definition(db, name="rent", auto_post=False)
    _due_definition(db, name="salary", entry_type="income", line_type="income", auto_post=False)
    _due_definition(db, name="automatic", auto_post=True)
    later, recurring = _definition(db, name="later", auto_post=False)
    recurring.next_due_date = date.today() + relativedelta(days=3)
    db.commit()
    start = (date.today() - relativedelta(months=2)).replace(day=1)
    _product(db, purchase_date=start, depreciation_start_date=start)

    by_link = {item["link"]: item for item in _recording_due(db)}

    assert set(by_link) == {"/db/definitions", "/db/definitions/income"}
    spending = by_link["/db/definitions"]
    assert spending["payload"]["count"] == 2
    assert "rent" in spending["body"] and "laptopの減価" in spending["body"] and "later" not in spending["body"]
    assert "automatic" not in spending["body"]
    assert by_link["/db/definitions/income"]["title"] == "記帳待ちが1件あります（収入）"


def test_automatic_or_blocked_write_downs_are_not_notified(db):
    start = (date.today() - relativedelta(months=2)).replace(day=1)
    automatic = _product(db, purchase_date=start, depreciation_start_date=start)
    workflow.set_auto_depreciation(db, 1, automatic.id, enabled=True, today=start)
    _product(db, name="broken", purchase_date=start, depreciation_start_date=start, depreciation_asset_account_id=None)
    assert _recording_due(db) == []


def test_recording_resolves_the_notification(db):
    from app.services import notification_service
    from app.workflows import notification_workflow

    period = date.today().strftime("%Y-%m")
    _, recurring = _due_definition(db, name="rent", auto_post=False)
    notification_workflow.sync(db, 1, period)
    [row] = db.query(models.Notification).filter_by(kind="recording_due").all()
    assert row.status == "open"

    recurring_service.process_one(db, recurring)
    notification_workflow.sync(db, 1, period)

    db.refresh(row)
    assert row.status == "done"
    assert [item for item in notification_service.visible(db, 1) if item.kind == "recording_due"] == []
