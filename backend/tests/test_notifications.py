"""Notifications keep the user's decision while generators recompute the reasons."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.services import notification_service as service

NOW = datetime(2026, 10, 18, 9, 0)


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
