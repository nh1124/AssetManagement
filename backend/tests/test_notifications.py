"""Notifications keep the user's decision while generators recompute the reasons."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services import data_health_service, notification_service as service
from app.workflows import notification_workflow as workflow

NOW = datetime(2026, 10, 18, 9, 0)
PERIOD = "2026-10"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=1, name="本人"), models.Client(id=2, name="別人")])
        session.commit()
        yield session
    engine.dispose()


def wanted(key="a", body="理由"):
    return [{"dedupe_key": key, "title": "題", "body": body, "payload": {"n": 1}, "link": "/goals"}]


def keys(db, client_id=1, now=NOW):
    return [row.dedupe_key for row in service.visible(db, client_id, now=now)]


def test_sync_creates_updates_and_resolves(db):
    service.sync(db, 1, "k", wanted(body="一"), now=NOW)
    service.sync(db, 1, "k", wanted(body="二"), now=NOW)
    (row,) = service.visible(db, 1, now=NOW)
    assert (row.body, row.status) == ("二", "open")
    service.sync(db, 1, "k", [], now=NOW)
    assert keys(db) == [] and row.status == "done"
    # The same reasons coming back reopen it.
    service.sync(db, 1, "k", wanted(), now=NOW)
    assert row.status == "open"


def test_snooze_hides_until_its_time(db):
    service.sync(db, 1, "k", wanted(), now=NOW)
    (row,) = service.visible(db, 1, now=NOW)
    service.decide(db, row, "snooze", until=NOW + timedelta(days=1), now=NOW)
    assert keys(db) == [] and service.hidden_count(db, 1, now=NOW) == 1
    assert keys(db, now=NOW + timedelta(days=1, minutes=1)) == ["a"]
    with pytest.raises(ValueError):
        service.decide(db, row, "snooze", until=NOW - timedelta(hours=1), now=NOW)


def test_dismissed_stays_hidden_while_reasons_hold_and_new_reasons_notify_again(db):
    service.sync(db, 1, "k", wanted("a"), now=NOW)
    (row,) = service.visible(db, 1, now=NOW)
    service.decide(db, row, "dismiss", now=NOW)
    service.sync(db, 1, "k", wanted("a"), now=NOW)
    assert keys(db) == []
    service.sync(db, 1, "k", wanted("b"), now=NOW)
    assert keys(db) == ["b"]
    service.decide(db, row, "reopen", now=NOW)
    assert row.status == "open"


def test_resolve_kind_and_clients_are_separate(db):
    service.sync(db, 1, "k", wanted(), now=NOW)
    service.sync(db, 2, "k", wanted(), now=NOW)
    service.resolve_kind(db, 1, "k", now=NOW)
    assert keys(db, 1) == [] and keys(db, 2) == ["a"]


def test_a_dismissal_ends_with_its_reasons(db):
    service.sync(db, 1, "k", wanted(), now=NOW)
    (row,) = service.visible(db, 1, now=NOW)
    service.decide(db, row, "dismiss", now=NOW)
    service.sync(db, 1, "k", wanted(), now=NOW)
    assert row.status == "dismissed"
    # The reasons went away and came back: that is a new occasion, shown again.
    service.sync(db, 1, "k", [], now=NOW)
    assert row.status == "done"
    service.sync(db, 1, "k", wanted(), now=NOW)
    assert keys(db) == ["a"]


def test_done_and_dismissed_rows_are_deleted_90_days_after_they_were_resolved(db):
    service.sync(db, 1, "k", wanted("a") + wanted("b") + wanted("c"), now=NOW)
    service.sync(db, 2, "k", wanted("a"), now=NOW)
    service.sync(db, 2, "k", [], now=NOW)
    a = next(row for row in service.visible(db, 1, now=NOW) if row.dedupe_key == "a")
    service.decide(db, a, "dismiss", now=NOW)
    service.sync(db, 1, "k", wanted("a") + wanted("c"), now=NOW)  # b is done
    service.purge(db, 1, now=NOW + timedelta(days=89))
    assert db.query(models.Notification).filter_by(client_id=1).count() == 3
    service.purge(db, 1, now=NOW + timedelta(days=90))
    assert [row.dedupe_key for row in db.query(models.Notification).filter_by(client_id=1)] == ["c"]
    # Another client's rows are its own.
    assert db.query(models.Notification).filter_by(client_id=2).count() == 1


def approval(db, client_id):
    row = models.AiChangeRequest(client_id=client_id, source="mcp", resource="transactions", action="create",
                                 risk="low", idempotency_key="k")
    db.add(row)
    return lambda: setattr(row, "status", "rejected")


def due_action(db, client_id):
    row = models.MonthlyAction(client_id=client_id, source_period="2026-09", target_period=PERIOD, proposal_id="p",
                               kind="capsule_contribution", description="積立", idempotency_key="k")
    # Next month's action is not due yet.
    db.add_all([row, models.MonthlyAction(client_id=client_id, source_period=PERIOD, target_period="2026-11",
                                          proposal_id="q", kind="capsule_contribution", idempotency_key="l")])
    return lambda: setattr(row, "status", "applied")


def unmatched(db, client_id):
    row = models.TransactionProposal(client_id=client_id, origin="recurring", date=date(2026, 10, 1),
                                     description="家賃", amount_minor=1000, legs=[], idempotency_key="k")
    db.add(row)
    return lambda: setattr(row, "status", "rejected")


def unclosed_month(db, client_id):
    db.add(models.Transaction(client_id=client_id, date=date(2026, 9, 30), description="食費", amount_minor=500))
    return lambda: db.add(models.PeriodClose(client_id=client_id, period="2026-09"))


@pytest.mark.parametrize("kind, seed, link", [
    (workflow.APPROVAL_PENDING, approval, "/automation/approvals"),
    (workflow.ACTIONS_DUE, due_action, "/budget/actions"),
    (workflow.UNMATCHED, unmatched, "/ledger/auto"),
    (workflow.MONTH_CLOSE, unclosed_month, "/ledger?month=2026-09"),
])
def test_each_kind_notifies_while_its_reasons_hold(db, kind, seed, link):
    generate = workflow.GENERATORS[kind]
    assert generate(db, 1, PERIOD) == []
    resolve = seed(db, 1)
    db.flush()
    (item,) = generate(db, 1, PERIOD)
    assert item["link"] == link and item["dedupe_key"].startswith(f"{kind}:")
    assert generate(db, 1, PERIOD) == [item]
    assert generate(db, 2, PERIOD) == []
    service.sync(db, 1, kind, [item], now=NOW)
    (row,) = service.visible(db, 1, now=NOW)
    resolve()
    db.flush()
    assert generate(db, 1, PERIOD) == []
    service.sync(db, 1, kind, [], now=NOW)
    assert row.status == "done"


def test_a_new_reason_is_a_new_notification_and_long_lists_end_in_a_count(db):
    for index in range(12):
        db.add(models.TransactionProposal(client_id=1, origin="recurring", date=date(2026, 10, 1), description=f"明細{index}",
                                          amount_minor=100, legs=[], idempotency_key=f"k{index}"))
    db.flush()
    (first,) = workflow.unmatched_notifications(db, 1, PERIOD)
    assert first["title"] == "未反映の候補が12件あります" and first["body"].splitlines()[-1] == "ほか2件"
    db.add(models.TransactionProposal(client_id=1, origin="recurring", date=date(2026, 10, 2), description="追加",
                                      amount_minor=100, legs=[], idempotency_key="new"))
    db.flush()
    (second,) = workflow.unmatched_notifications(db, 1, PERIOD)
    assert second["dedupe_key"] != first["dedupe_key"]


def test_data_health_notifies_warnings_and_errors_only(db, monkeypatch):
    issues = [
        {"code": "journal_unbalanced", "severity": "error", "title": "不一致", "count": 2},
        {"code": "advance_pair_candidate", "severity": "info", "title": "立替", "count": 5},
        {"code": "duplicate_recurring", "severity": "warning", "title": "重複", "count": 0},
    ]
    monkeypatch.setattr(data_health_service, "check_data_health", lambda db, client_id: {"issues": issues})
    (item,) = workflow.data_health_notifications(db, 1, PERIOD)
    assert (item["body"], item["link"], item["payload"]) == ("不一致（2件）", "/debug/data-health", {"codes": ["journal_unbalanced"], "count": 1})
    issues[0]["count"] = 0
    assert workflow.data_health_notifications(db, 1, PERIOD) == []
