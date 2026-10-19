"""WP21: which accounts pay a life event is the simulation setting's (資金の割り当て), not the event's."""
from datetime import date
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI

from app import models, schemas
from app.database import get_db
from app.dependencies import get_current_client
from app.domain.errors import DomainError, NotFound, Refused, detail_for, status_for
from app.domain.journal import Leg
from app.domain.transfer import migrate_event_fundings
from app.routers.life_events import router as events_router
from app.services import capsule_service, event_funding_service as fundings
from app.services import contribution_plan_service as plans
from app.services import goal_service, life_scenario_service as scenarios
from app.services.ledger_service import create_transaction
from app.workflows import goal_budget_workflow
from fastapi.responses import JSONResponse
from scenario_fixtures import account, db, request  # noqa: F401

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")


def months_ahead(months: int) -> date:
    index = TODAY.year * 12 + TODAY.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def goal(db, name="ゴール", is_goal=True):
    scenario = models.LifeScenario(client_id=1, name=name, is_goal=is_goal, annual_return=0, inflation=0, horizon_years=3)
    db.add(scenario)
    db.add(models.SimulationConfig(client_id=1, volatility=0, tax_rate=0))
    db.commit()
    return scenario


def event(db, scenario, name, amount, when, **values):
    return goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(
        scenario_id=scenario.id, name=name, target_amount=amount, target_date=when, **values))


def share(*pairs):
    return [schemas.LifeEventFundingInput(account_id=account_id, share=value) for account_id, value in pairs]


def test_an_event_takes_shares_of_asset_accounts_up_to_100_percent(db):
    scenario = goal(db)
    savings, securities = account(db, "貯蓄"), account(db, "証券")
    food, theirs = account(db, "食費", kind="expense"), account(db, "他人の口座", client_id=2)
    wedding = event(db, scenario, "結婚", 1_000_000, months_ahead(12))
    row = fundings.set_fundings(db, 1, wedding.id, share((securities.id, 60), (savings.id, 40)))
    assert [(item.account_id, item.share, item.account_name) for item in row.fundings] == [(securities.id, 60.0, "証券"), (savings.id, 40.0, "貯蓄")]
    with pytest.raises(Refused):
        fundings.set_fundings(db, 1, wedding.id, share((securities.id, 60), (savings.id, 50)))
    with pytest.raises(Refused):
        fundings.set_fundings(db, 1, wedding.id, share((savings.id, 50), (savings.id, 50)))
    for wrong in (food.id, theirs.id):
        with pytest.raises(NotFound):
            fundings.set_fundings(db, 1, wedding.id, share((wrong, 10)))
    with pytest.raises(NotFound):
        fundings.set_fundings(db, 2, wedding.id, share((savings.id, 10)))
    # A refused change leaves the shares as they were; an empty list clears them.
    assert [item.share for item in db.get(models.LifeEvent, wedding.id).fundings] == [60.0, 40.0]
    assert fundings.set_fundings(db, 1, wedding.id, []).fundings == []


def test_the_simulation_moves_each_share_through_its_account_and_the_rest_through_net_worth(db):
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=1_000_000)
    securities = account(db, "証券", balance=1_000_000)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "annual_return": 0})
    trip = event(db, scenario, "旅行", 200_000, date(TODAY.year + 1, 1, 1))
    # securities has no 積立設定: naming it in a share makes it a 使用口座.
    fundings.set_fundings(db, 1, trip.id, share((savings.id, 50), (securities.id, 25)))
    result = scenarios.project(db, 1, scenario)
    by_account = {row["account_id"]: row["p50"] for row in result["accounts"]}
    assert by_account[savings.id][:2] == [1_000_000, 900_000]
    assert by_account[securities.id][:2] == [1_000_000, 950_000]
    assert result["projection"][1]["p50"] == 2_000_000 - 200_000
    assert next(row for row in result["events"] if row["name"] == "旅行")["fundings"] == [
        {"account_id": savings.id, "share": 50.0}, {"account_id": securities.id, "share": 25.0}]


def test_the_plan_earmarks_each_share_in_its_account_and_follows_changed_shares(db):
    scenario = goal(db)
    savings, securities = account(db, "貯蓄", balance=500_000), account(db, "証券", balance=500_000)
    car = event(db, scenario, "車", 120_000, months_ahead(12))
    fundings.set_fundings(db, 1, car.id, share((savings.id, 75), (securities.id, 25)))
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    assert sorted((row["kind"], row["account_id"], row["new"], row["new_capsule"]) for row in preview["changes"]) == [
        ("capsule", savings.id, 7500, True), ("capsule", securities.id, 2500, True)]
    goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])
    capsule = capsule_service.goal_capsules(db, 1, [car.id])[car.id]
    assert capsule.name == "車" and capsule.monthly_contribution_minor == 10000
    assert {(source.account_id, source.target_amount_minor) for source in capsule.funding_sources} == {(savings.id, 90000), (securities.id, 30000)}
    rows = db.query(models.MonthlyPlanLine).filter_by(client_id=1, source_kind="goal", is_active=True).all()
    assert {(row.target_id, row.account_id, row.amount_minor) for row in rows} == {(capsule.id, savings.id, 7500), (capsule.id, securities.id, 2500)}

    # Money set aside in securities stays claimed there when the event drops the account.
    transaction = create_transaction(db, client_id=1, date=TODAY, description="確保", amount_minor=1000, currency="JPY",
                                     legs=[Leg(securities.id, debit=1000, capsule_id=capsule.id), Leg(securities.id, credit=1000)])
    db.commit()
    assert transaction.id
    fundings.set_fundings(db, 1, car.id, share((savings.id, 100)))
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])
    db.refresh(capsule)
    assert {(source.account_id, source.target_amount_minor) for source in capsule.funding_sources} == {(savings.id, 120000), (securities.id, 0)}
    rows = db.query(models.MonthlyPlanLine).filter_by(client_id=1, source_kind="goal", is_active=True).all()
    assert {(row.account_id, row.amount_minor) for row in rows} == {(savings.id, 10000)}


def test_only_expenses_with_accounts_are_earmarked_and_a_copy_keeps_the_shares(db):
    scenario = goal(db)
    savings = account(db, "貯蓄")
    unfunded = event(db, scenario, "未定", 50_000, months_ahead(6))
    bonus = event(db, scenario, "臨時収入", 80_000, months_ahead(6), direction="income")
    fundings.set_fundings(db, 1, bonus.id, share((savings.id, 100)))
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    assert [row for row in preview["changes"] if row["kind"] == "capsule"] == []
    fundings.set_fundings(db, 1, unfunded.id, share((savings.id, 30)))
    copy = scenarios.duplicate(db, 1, scenario.id, "複製")
    copied = {row.name: row for row in db.query(models.LifeEvent).filter_by(scenario_id=copy.id)}
    assert [(item.account_id, item.share_bp) for item in copied["未定"].fundings] == [(savings.id, 3000)]
    assert [(item.account_id, item.share_bp) for item in copied["臨時収入"].fundings] == [(savings.id, 10000)]


def test_an_older_backup_turns_an_event_account_into_a_whole_share():
    data = migrate_event_fundings({
        "accounts": [{"id": 1, "account_type": "asset"}, {"id": 2, "account_type": "expense"}],
        "life_events": [{"id": 5, "account_id": 1}, {"id": 6, "account_id": 2}, {"id": 7, "account_id": None}],
    })
    assert data["life_event_fundings"] == [{"id": 1, "life_event_id": 5, "account_id": 1, "share_bp": 10000}]
    assert all("account_id" not in row for row in data["life_events"])


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261020_0081_event_fundings.py"
    spec = importlib.util.spec_from_file_location("wp21_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_moves_each_event_account_into_a_whole_share_and_back():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_type VARCHAR)",
            "CREATE TABLE life_events (id INTEGER PRIMARY KEY, client_id INTEGER, account_id INTEGER,"
            " CONSTRAINT fk_life_events_account_id FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE SET NULL)",
            "INSERT INTO accounts VALUES (1, 'asset'), (2, 'asset')",
            "INSERT INTO life_events VALUES (5, 1, 1), (6, 1, NULL)",
        ):
            connection.exec_driver_sql(statement)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        assert connection.exec_driver_sql("SELECT life_event_id, account_id, share_bp FROM life_event_fundings").all() == [(5, 1, 10000)]
        assert "account_id" not in {column["name"] for column in sa.inspect(connection).get_columns("life_events")}
        connection.exec_driver_sql("INSERT INTO life_event_fundings (life_event_id, account_id, share_bp) VALUES (6, 1, 3000), (6, 2, 7000)")
        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()
        assert connection.exec_driver_sql("SELECT id, account_id FROM life_events ORDER BY id").all() == [(5, 1), (6, 2)]
        assert "life_event_fundings" not in sa.inspect(connection).get_table_names()
    engine.dispose()


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(events_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})
    return app


def test_http_sets_and_lists_an_events_accounts(db, api):
    scenario = goal(db)
    savings = account(db, "貯蓄")
    wedding = event(db, scenario, "結婚", 1_000_000, months_ahead(12))
    response = request(api, "PUT", f"/life-events/{wedding.id}/fundings", json=[{"account_id": savings.id, "share": 70}])
    assert response.status_code == 200
    assert response.json()["fundings"] == [{"account_id": savings.id, "account_name": "貯蓄", "share": 70.0}]
    listed = request(api, "GET", "/life-events/", params={"scenario_id": scenario.id}).json()
    assert listed[0]["fundings"][0]["share"] == 70.0 and "account_id" not in listed[0]
    progress = request(api, "GET", "/life-events/with-progress").json()
    assert progress[0]["fundings"] == [{"account_id": savings.id, "account_name": "貯蓄", "share": 70.0}]
    assert request(api, "PUT", f"/life-events/{wedding.id}/fundings", json=[{"account_id": savings.id, "share": 120}]).status_code == 422
    assert request(api, "POST", "/life-events/", json={"scenario_id": scenario.id, "name": "x", "target_date": "2030-01-01",
                                                       "target_amount": 1, "account_id": savings.id}).status_code == 422
