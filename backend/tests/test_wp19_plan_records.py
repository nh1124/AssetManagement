"""WP19: the plan page's account editor -- an account's month as records, only the user's written here."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import DomainError, detail_for, status_for
from app.routers.plan import router as plan_router
from app.services.budget_plan_store import resolve_budget_plan_id

PERIOD = "2026-11"


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
        models.Account(id=1, client_id=1, name="貯蓄口座", account_type="asset"),
        models.Account(id=2, client_id=1, name="食費", account_type="expense"),
        models.Account(id=3, client_id=1, name="メイン銀行", account_type="asset"),
        models.Account(id=4, client_id=2, name="他人の口座", account_type="asset"),
    ])
    session.commit()
    plan_id = resolve_budget_plan_id(session, 1)
    session.add(models.MonthlyPlanLine(
        client_id=1, plan_id=plan_id, target_period=PERIOD, line_type="allocation", target_type="account",
        account_id=1, name="貯蓄口座", amount_minor=20000, source="goal", source_kind="goal",
    ))
    session.add(models.RegistryEntry(
        client_id=1, name="食材の宅配", amount_minor=8000, budget_account_id=2, source_account_id=3,
        start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly",
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(plan_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    def domain_error(_request, exc):
        return JSONResponse(status_code=status_for(exc), content={"detail": detail_for(exc)})

    return TestClient(app)


def _section(view: dict, key: str) -> dict:
    return next(section for section in view["sections"] if section["key"] == key)


def test_asset_sections_list_the_goal_record_read_only(api):
    view = api.get(f"/plan/{PERIOD}/accounts/1").json()
    assert [(s["key"], s["label"]) for s in view["sections"]] == [("allocation", "予算"), ("drawdown", "取り崩し")]
    allocation = _section(view, "allocation")
    assert allocation["total"] == 20000
    [record] = allocation["records"]
    assert (record["origin"], record["origin_label"], record["editable"]) == ("goal", "ゴールによる設定", False)
    assert allocation["can_add"] is True
    assert _section(view, "drawdown")["records"] == []


def test_user_records_are_added_amended_and_deleted_one_per_name(api):
    added = api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "allocation", "amount": 5000})
    assert added.status_code == 200
    allocation = _section(added.json(), "allocation")
    assert allocation["total"] == 25000 and allocation["can_add"] is True
    mine = next(record for record in allocation["records"] if record["origin"] == "manual")
    assert mine["editable"] and mine["origin_label"] == "ユーザーによる追加"
    # A second record needs its own name (reason): the same one is refused.
    again = api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "allocation", "amount": 1})
    assert again.status_code == 409 and "名前" in again.json()["detail"]

    amended = api.put(f"/plan/records/{mine['id']}", json={"amount": 6000, "name": "ボーナス分"}).json()
    record = next(r for r in _section(amended, "allocation")["records"] if r["origin"] == "manual")
    assert (record["amount"], record["name"]) == (6000, "ボーナス分")

    drawdown = api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "drawdown", "amount": 3000}).json()
    assert _section(drawdown, "drawdown")["total"] == 3000

    removed = api.delete(f"/plan/records/{mine['id']}").json()
    assert [r["origin"] for r in _section(removed, "allocation")["records"]] == ["goal"]


def test_goal_and_automatic_records_are_changed_where_they_come_from(api):
    goal = _section(api.get(f"/plan/{PERIOD}/accounts/1").json(), "allocation")["records"][0]
    assert goal["id"] is not None
    assert api.put(f"/plan/records/{goal['id']}", json={"amount": 1}).status_code == 422
    assert api.delete(f"/plan/records/{goal['id']}").status_code == 422

    food = api.get(f"/plan/{PERIOD}/accounts/2").json()
    [record] = _section(food, "expense")["records"]
    assert (record["origin"], record["name"], record["amount"], record["editable"]) == ("registry", "食材の宅配", 8000, False)
    assert [item["name"] for item in food["scheduled"]] == ["食材の宅配"]
    # The paying account sees the same automatic transaction.
    assert [item["name"] for item in api.get(f"/plan/{PERIOD}/accounts/3").json()["scheduled"]] == ["食材の宅配"]


def test_refusals(api):
    assert api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "expense", "amount": 1}).status_code == 422
    assert api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "allocation", "amount": -1}).status_code == 422
    assert api.post("/plan/records", json={"period": "2026-13", "account_id": 1, "section": "allocation", "amount": 1}).status_code == 422
    assert api.get(f"/plan/{PERIOD}/accounts/4").status_code == 404
    assert api.post("/plan/records", json={"period": PERIOD, "account_id": 4, "section": "allocation", "amount": 1}).status_code == 404
    assert api.put("/plan/records/999", json={"amount": 1}).status_code == 404


def test_a_user_record_adds_to_the_automatic_transaction_beside_it(api):
    view = api.post("/plan/records", json={"period": PERIOD, "account_id": 2, "section": "expense", "amount": 2000}).json()
    expense = _section(view, "expense")
    assert sorted((r["origin"], r["amount"]) for r in expense["records"]) == [("manual", 2000), ("registry", 8000)]
    assert expense["total"] == 10000


def test_several_user_records_in_one_section_each_with_its_reason(api):
    """WP27: the user's records are told apart by name, so a budget can say what it is for."""
    api.post("/plan/records", json={"period": PERIOD, "account_id": 2, "section": "expense", "amount": 30000, "name": "日々の食費"})
    view = api.post("/plan/records", json={"period": PERIOD, "account_id": 2, "section": "expense", "amount": 10000, "name": "帰省の外食"}).json()
    expense = _section(view, "expense")
    assert sorted((r["name"], r["amount"]) for r in expense["records"] if r["origin"] == "manual") == [("帰省の外食", 10000), ("日々の食費", 30000)]
    assert expense["total"] == 48000


def test_an_automatic_record_becomes_an_automatic_transaction_that_only_budgets_unless_asked(api, db):
    from app.workflows.automatic_recording_workflow import process_due
    budget_only = api.post("/plan/records", json={"period": PERIOD, "account_id": 2, "section": "expense", "amount": 40000, "name": "食費",
                                                  "automatic": {"start_period": PERIOD, "counter_account_id": 1}})
    assert budget_only.status_code == 200
    entry = db.query(models.RegistryEntry).filter_by(client_id=1, name="食費").one()
    assert (entry.kind, entry.source_account_id, entry.destination_account_id, entry.records_transactions) == ("expense", 1, 2, False)
    # It budgets every month as 自動取引による設定 but never posts.
    later = api.get("/plan/2027-03/accounts/2").json()
    assert ("食費", 40000, "registry") in {(r["name"], r["amount"], r["origin"]) for r in _section(later, "expense")["records"]}
    process_due(db, 1, today=date(2027, 4, 1))
    assert db.query(models.Transaction).filter_by(registry_entry_id=entry.id).count() == 0
    assert next(item for item in later["scheduled"] if item["name"] == "食費")["records_transactions"] is False
    # Without the other side it cannot be made; with 取引も記録する it posts like any automatic transaction.
    refused = api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "allocation", "amount": 10000, "name": "積立",
                                              "automatic": {"start_period": PERIOD, "records_transactions": True}})
    assert refused.status_code == 422 and "相手の口座" in refused.json()["detail"]
    api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "allocation", "amount": 10000, "name": "積立",
                                    "automatic": {"start_period": PERIOD, "end_period": "2027-01", "counter_account_id": 3, "records_transactions": True,
                                                  "day_of_month": 25}})
    posting = db.query(models.RegistryEntry).filter_by(client_id=1, name="積立").one()
    assert (posting.kind, posting.source_account_id, posting.destination_account_id, posting.end_date) == ("transfer", 3, 1, date(2027, 1, 31))
    process_due(db, 1, today=date(2027, 4, 1))
    assert db.query(models.Transaction).filter_by(registry_entry_id=posting.id).count() == 3
    # 借入・取り崩し are not made automatic here.
    assert api.post("/plan/records", json={"period": PERIOD, "account_id": 1, "section": "drawdown", "amount": 1,
                                           "automatic": {"start_period": PERIOD, "counter_account_id": 3}}).status_code == 422


def test_the_migration_gives_manual_rows_their_named_identity():
    import importlib.util
    from pathlib import Path as FilePath
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location("named_records", FilePath(__file__).parents[1] / "alembic/versions/20261021_0087_budget_only_automatic.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE registry_entries (id INTEGER PRIMARY KEY, name VARCHAR)")
        connection.exec_driver_sql("CREATE TABLE monthly_plan_lines (id INTEGER PRIMARY KEY, plan_id INTEGER, target_period VARCHAR, source_kind VARCHAR,"
                                   " line_type VARCHAR, target_type VARCHAR, account_id INTEGER, source_account_id INTEGER, target_id INTEGER,"
                                   " name VARCHAR, cash_treatment VARCHAR, identity_key VARCHAR)")
        connection.exec_driver_sql("INSERT INTO monthly_plan_lines VALUES (1, 5, '2026-11', 'manual', 'expense', 'account', 2, NULL, NULL, ' 外食 ', 'auto', 'old'),"
                                   " (2, 5, '2026-11', 'goal', 'allocation', 'account', 1, NULL, NULL, 'ゴール', 'auto', 'kept')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        keys = connection.exec_driver_sql("SELECT identity_key FROM monthly_plan_lines ORDER BY id").scalars().all()
        assert "records_transactions" in {column["name"] for column in sa.inspect(connection).get_columns("registry_entries")}
    engine.dispose()
    from app.services.budget_lines import plan_line_identity_key
    assert keys == [plan_line_identity_key({"plan_id": 5, "target_period": "2026-11", "source_kind": "manual", "line_type": "expense",
                                            "target_type": "account", "account_id": 2, "name": " 外食 ", "cash_treatment": "auto"}), "kept"]

