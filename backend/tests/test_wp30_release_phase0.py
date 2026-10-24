"""Release boundaries: user data checks, administrator repairs and development defaults."""
import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.config import AppConfig
from app.database import Base
from app.domain.journal import Leg
from app.main import api_docs_urls
from app.routers import data_transfer
from app.services import data_health_service as health, notification_service
from app.services.ledger_service import create_transaction
from app.workflows import notification_workflow as notifications


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add_all([
            models.Client(id=1, name="dev", general_settings={"language": "ja", "currency": "JPY"}),
            models.Client(id=2, name="other", is_active=True),
            models.Client(id=3, name="inactive", is_active=False),
            models.Account(id=1, client_id=1, name="Bank", account_type="asset"),
        ])
        session.commit()
        yield session
    engine.dispose()


def capsule_without_account(capsule_id, name):
    return [
        models.Capsule(id=capsule_id, client_id=1, name=name, target_amount_minor=1000),
        models.CapsuleRule(client_id=1, capsule_id=capsule_id, destination_account_id=1,
                           trigger_type="Income", amount_type="fixed", amount_minor=100, is_active=True),
    ]


def capsule_short_of_target(capsule_id, name):
    return [
        models.Capsule(id=capsule_id, client_id=1, name=name, target_amount_minor=1000),
        models.CapsuleFundingSource(client_id=1, capsule_id=capsule_id, account_id=1, target_amount_minor=500),
    ]


def seed_issues(db):
    db.add_all([
        *capsule_without_account(1, "Travel"),
        *capsule_short_of_target(2, "Home"),
        # An admin-only duplicate issue coexists with the two user-facing issues.
        *[models.MonthlyPlanLine(client_id=1, target_period="2026-09", line_type="income",
                                name="Duplicate", amount_minor=100, identity_key="") for _ in range(2)],
    ])
    db.commit()


def snapshot(db):
    return {table.name: [dict(row) for row in db.execute(sa.select(table)).mappings()]
            for table in Base.metadata.sorted_tables}


def test_audience_and_summary_use_only_returned_issues(db):
    seed_issues(db)
    expected = frozenset({
        "capsule_without_account", "capsule_claim_negative_on_account",
        "capsule_beyond_its_declared_share", "capsule_plan_does_not_total_its_target",
        "capsule_funding_account_is_inactive",
        "account_earmarked_beyond_its_balance",
    })
    assert health.USER_CODES == expected
    assert isinstance(health.USER_CODES, frozenset)
    all_issues = health.check_data_health(db, 1)["issues"]
    assert all(issue["audience"] == ("user" if issue["code"] in expected else "admin") for issue in all_issues)
    result = health.check_data_health(db, 1, audience="user")
    assert set(issue["code"] for issue in result["issues"]) == expected
    assert result["total_issues"] == 2
    assert result["repairable_groups"] == 0
    assert result["status"] == "issues_found"
    clean = health.check_data_health(db, 2, audience="user")
    assert (clean["status"], clean["total_issues"], clean["repairable_groups"]) == ("ok", 0, 0)


def test_every_user_code_has_notification_text_and_localized_title():
    assert health.USER_CODES <= notifications.DATA_HEALTH_TEXT.keys()
    assert health.USER_CODES <= health.TITLES.keys()
    assert health.USER_CODES == notifications.DATA_HEALTH_ITEMS.keys()


@pytest.mark.parametrize("language,title,lead,issue_title", [
    ("ja", "口座の残高より多く取り置いています（1口座）",
     "取り置いた分まで使っています。資産 › 口座で確保額を減らすか、口座にお金を戻してください。",
     "口座の残高を超えて取り置いている"),
    ("en", "Accounts with more set aside than they hold (1)",
     "Money set aside has been spent. Reduce what is set aside under Assets › Accounts, or move money back into the account.",
     "Account holds less than its earmarks"),
])
def test_spent_earmarked_money_notifies_per_account(db, language, title, lead, issue_title):
    db.get(models.Client, 1).general_settings = {"language": language, "currency": "JPY"}
    db.add_all([
        models.Account(id=2, client_id=1, name="Income", account_type="income"),
        models.Account(id=3, client_id=1, name="Spending", account_type="expense"),
        models.Capsule(id=1, client_id=1, name="Travel", target_amount_minor=1000),
    ])
    db.flush()
    create_transaction(db, client_id=1, date=date(2026, 10, 1), description="Set aside",
                       amount_minor=1000, currency="JPY",
                       legs=[Leg(1, debit=1000, capsule_id=1), Leg(2, credit=1000)])
    create_transaction(db, client_id=1, date=date(2026, 10, 2), description="Spent from account",
                       amount_minor=400, currency="JPY",
                       legs=[Leg(3, debit=400), Leg(1, credit=400)])
    db.flush()
    code = "account_earmarked_beyond_its_balance"
    issue = next(issue for issue in health.check_data_health(db, 1, audience="user")["issues"]
                 if issue["code"] == code)
    assert (issue["audience"], issue["severity"], issue["title"], issue["count"]) == (
        "user", "error", issue_title, 1)
    assert "capsule_id" not in issue["items"][0]
    (row,) = notifications.data_health_notifications(db, 1, "2026-10")
    assert row["title"] == title
    assert row["body"].splitlines() == [lead, "Bank"]
    assert row["link"] == "/assets/accounts"
    assert row["payload"] == {"code": code, "ids": [1], "count": 1}
    key = row["dedupe_key"]
    db.get(models.Client, 1).general_settings = {"language": "en" if language == "ja" else "ja"}
    db.flush()
    (translated,) = notifications.data_health_notifications(db, 1, "2026-10")
    assert translated["dedupe_key"] == key


def test_two_user_notifications_and_old_notification_resolves_on_sync(db):
    seed_issues(db)
    old_key = "data_health:" + hashlib.sha256(json.dumps(
        sorted(["capsule_plan_does_not_total_its_target", "capsule_without_account", "duplicate_plan_lines"])
    ).encode()).hexdigest()[:16]
    notification_service.sync(db, 1, "data_health", [{
        "dedupe_key": old_key, "title": "Old", "body": "Old aggregate", "payload": {},
        "link": "/obsolete",
    }])
    db.commit()
    notifications.sync(db, 1, "2026-10")
    old = db.query(models.Notification).filter_by(dedupe_key=old_key).one()
    assert old.status == "done"
    rows = db.query(models.Notification).filter_by(kind="data_health", status="open").all()
    assert len(rows) == 2
    by_code = {row.payload["code"]: row for row in rows}
    short = by_code["capsule_plan_does_not_total_its_target"]
    earmark = by_code["capsule_without_account"]
    assert short.link == "/db/earmarks"
    assert short.title == "資金元の額の合計が目標額と合わない取り置きがあります（1件）"
    assert short.body.splitlines() == [
        "目標額を変えたときは、資金元の額も合わせてください。",
        "Home",
    ]
    assert short.payload == {"code": "capsule_plan_does_not_total_its_target", "ids": [2], "count": 1}
    assert earmark.link == "/db/earmarks"
    assert earmark.title == "確保する口座が決まっていない取り置きがあります（1件）"
    assert earmark.body.splitlines() == [
        "取り置きを開いて、確保する口座を設定してください。口座が決まるまで規則は何も確保しません。",
        "Travel",
    ]
    assert earmark.payload == {"code": "capsule_without_account", "ids": [1], "count": 1}


def test_admin_only_issues_never_notify(db):
    seed_issues(db)
    db.query(models.CapsuleRule).delete()
    db.query(models.CapsuleFundingSource).delete()
    db.commit()
    assert any(i["count"] for i in health.check_data_health(db, 1)["issues"])
    assert notifications.data_health_notifications(db, 1, "2026-10") == []


def test_health_dismissal_holds_and_new_item_notifies(db):
    seed_issues(db)
    wanted = notifications.data_health_notifications(db, 1, "2026-10")
    notification_service.sync(db, 1, "data_health", wanted)
    rows = db.query(models.Notification).filter_by(kind="data_health").all()
    for row in rows:
        notification_service.decide(db, row, "dismiss")
    notification_service.sync(db, 1, "data_health", notifications.data_health_notifications(db, 1, "2026-10"))
    assert notification_service.visible(db, 1) == []
    db.add_all(capsule_short_of_target(3, "Car"))
    db.flush()
    notification_service.sync(db, 1, "data_health", notifications.data_health_notifications(db, 1, "2026-10"))
    (new,) = notification_service.visible(db, 1)
    assert new.payload["code"] == "capsule_plan_does_not_total_its_target"
    assert new.payload["count"] == 2


@pytest.mark.parametrize("language", ["ja", "en"])
@pytest.mark.parametrize("code", sorted(health.USER_CODES))
def test_each_health_message_preserves_lead_count_and_language(db, monkeypatch, language, code):
    db.get(models.Client, 1).general_settings = {"language": language}
    if code == "account_earmarked_beyond_its_balance":
        items = [{"account_id": i, "account_name": f"Bank {i}", "currency": "JPY",
                  "capsules": [{"capsule_id": 1000 + i, "name": f"Earmark {i}"}]} for i in range(1, 101)]
    else:
        items = [{"capsule_id": i, "name": f"Earmark {i}", "account_name": "Bank", "account_id": 1}
                 for i in range(1, 101)]
    issue = {"code": code, "severity": "error" if code == "account_earmarked_beyond_its_balance" else "warning",
             "count": 105, "items": items}
    def checked(db, client_id, *, audience):
        assert audience == "user"
        issue["fingerprint"] = health.issue_fingerprint(issue["items"])
        return {"issues": [issue]}
    monkeypatch.setattr(health, "check_data_health", checked)
    (row,) = notifications.data_health_notifications(db, 1, "2026-10")
    titles, leads, link = notifications.DATA_HEALTH_TEXT[code]
    index = language == "en"
    assert row["title"] == titles[index].format(n=105)
    lines = row["body"].splitlines()
    assert lines[0] == leads[index]
    assert len(lines) == notifications.BODY_LINES + 2
    assert lines[-1] == ("and 90 more" if index else "ほか90件")
    assert row["payload"]["count"] == 105
    if code == "account_earmarked_beyond_its_balance":
        assert row["link"] == "/assets/accounts"
        assert lines[1] == "Bank 1"
        assert row["payload"]["ids"] == list(range(1, 101))
        items[0]["account_id"] = 200
        (changed_account,) = notifications.data_health_notifications(db, 1, "2026-10")
        assert changed_account["dedupe_key"] != row["dedupe_key"]
        items[0]["account_id"] = 1
        items[0]["currency"] = "USD"
        (changed_currency,) = notifications.data_health_notifications(db, 1, "2026-10")
        assert changed_currency["dedupe_key"] != row["dedupe_key"]
    else:
        assert row["link"] == link
        if code in ("capsule_without_account", "capsule_plan_does_not_total_its_target"):
            assert lines[1] == "Earmark 1"
        else:
            assert lines[1] == ("Earmark 1 (Bank)" if index else "Earmark 1（Bank）")
    issue["severity"] = "info"
    assert notifications.data_health_notifications(db, 1, "2026-10") == []
    issue.update(severity="warning", count=0)
    assert notifications.data_health_notifications(db, 1, "2026-10") == []


def test_api_is_user_only_and_repair_route_is_removed(db):
    seed_issues(db)
    app = FastAPI()
    app.include_router(data_transfer.router)
    app.dependency_overrides[data_transfer.get_db] = lambda: db
    app.dependency_overrides[data_transfer.get_current_client] = lambda: db.get(models.Client, 1)
    with TestClient(app) as http:
        response = http.get("/data/health")
        assert response.status_code == 200
        assert {i["code"] for i in response.json()["issues"]} == health.USER_CODES
        assert http.post("/data/health/repair", json={}).status_code in (404, 405)


@pytest.mark.parametrize("production", [False, True])
def test_api_docs_urls(production):
    config = AppConfig(app_env="production" if production else "development")
    expected = {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    assert api_docs_urls(config) == ({key: None for key in expected} if production else expected)


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
@pytest.mark.parametrize("guard", ["none", "username", "name", "both", "different", "missing"])
def test_seed_migration_guarded_sql(direction, guard):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261022_0088_dev_seed.py"
    spec = importlib.util.spec_from_file_location("wp30_seed", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261021_0087"
    old_user, old_name, new_user, new_name = (
        ("admin", "Default User", "dev", "dev") if direction == "upgrade"
        else ("dev", "dev", "admin", "Default User")
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE clients (id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT UNIQUE)"))
        username, name = ("owner", "Owner") if guard == "different" else (old_user, old_name)
        if guard != "missing":
            connection.execute(sa.text("INSERT INTO clients VALUES (1, :username, :name)"),
                               {"username": username, "name": name})
        other = {"username": new_user if guard in ("username", "both") else "other",
                 "name": new_name if guard in ("name", "both") else "Other"}
        connection.execute(sa.text("INSERT INTO clients VALUES (2, :username, :name)"), other)
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, direction)()
        row = connection.execute(sa.text("SELECT username, name FROM clients WHERE id = 1")).first()
        if guard == "missing":
            assert row is None
        elif guard == "different":
            assert tuple(row) == (username, name)
        else:
            assert tuple(row) == (
                old_user if guard in ("username", "both") else new_user,
                old_name if guard in ("name", "both") else new_name,
            )
        assert tuple(connection.execute(sa.text("SELECT username, name FROM clients WHERE id = 2")).one()) == (
            other["username"], other["name"])
    engine.dispose()


def test_unsampled_health_identity_changes_fingerprint_and_notification(db):
    for i in range(1, 102):
        db.add_all(capsule_without_account(i, f"Earmark {i}"))
    db.commit()
    def issue():
        return next(row for row in health.check_data_health(db, 1, audience="user")["issues"]
                    if row["code"] == "capsule_without_account")
    before = issue()
    assert before["count"] == 101 and len(before["items"]) == 100
    (old,) = notifications.data_health_notifications(db, 1, "2026-10")
    notification_service.sync(db, 1, "data_health", [old])
    db.query(models.Notification).filter_by(dedupe_key=old["dedupe_key"]).one().status = "dismissed"
    db.query(models.CapsuleRule).filter_by(capsule_id=101).delete()
    db.delete(db.get(models.Capsule, 101))
    db.add_all(capsule_without_account(102, "Replacement"))
    db.commit()
    after = issue()
    assert before["items"] == after["items"] and before["count"] == after["count"]
    assert before["fingerprint"] != after["fingerprint"]
    (new,) = notifications.data_health_notifications(db, 1, "2026-10")
    assert new["dedupe_key"] != old["dedupe_key"]
    notification_service.sync(db, 1, "data_health", [new])
    assert notification_service.visible(db, 1)[0].dedupe_key == new["dedupe_key"]


def test_health_fingerprint_ignores_order_and_names_but_tracks_claim_identity():
    items = [{"capsule_id": 1, "account_id": 2, "currency": "JPY", "name": "Trip"},
             {"capsule_id": 3, "account_id": 4, "currency": "USD", "name": "Home"}]
    before = health.issue_fingerprint(items)
    items.reverse()
    items[0]["name"] = "Renamed"
    assert health.issue_fingerprint(items) == before
    items[0]["currency"] = "JPY"
    assert health.issue_fingerprint(items) != before
