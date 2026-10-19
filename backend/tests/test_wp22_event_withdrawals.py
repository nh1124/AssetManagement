"""WP22: what an account gives toward a life event is a 積立設定 record (ライフイベントへの取り崩し)."""
from datetime import date
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import models, schemas
from app.database import get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, Refused, detail_for, status_for
from app.domain.journal import Leg
from app.domain.transfer import migrate_event_fundings, migrate_event_withdrawals
from app.routers.life_events import router as events_router
from app.routers.life_scenarios import router as scenarios_router
from app.services import capsule_service
from app.services import contribution_plan_service as plans
from app.services import goal_service, life_scenario_service as scenarios
from app.services.ledger_service import create_transaction
from app.workflows import goal_budget_workflow
from scenario_fixtures import account, db, request  # noqa: F401

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")


def months_ahead(months: int) -> date:
    index = TODAY.year * 12 + TODAY.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def month(when: date) -> str:
    return when.strftime("%Y-%m")


def goal(db, name="ゴール", is_goal=True):
    scenario = models.LifeScenario(client_id=1, name=name, is_goal=is_goal, annual_return=0, inflation=0, horizon_years=3)
    db.add(scenario)
    if db.query(models.SimulationConfig).filter_by(client_id=1).first() is None:
        db.add(models.SimulationConfig(client_id=1, volatility=0, tax_rate=0))
    db.commit()
    return scenario


def event(db, scenario, name, amount, when, **values):
    return goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(
        scenario_id=scenario.id, name=name, target_amount=amount, target_date=when, **values))


def withdraw(db, scenario, account_id, when, amount, event_id, **values):
    return plans.create_plan(db, 1, scenario.id, {"account_id": account_id, "start_period": month(when),
                                                   "monthly_amount": -amount, "life_event_id": event_id, **values})


def test_a_withdrawal_record_takes_money_once_for_an_expense_of_its_scenario(db):
    scenario, other = goal(db), goal(db, "別", is_goal=False)
    savings, food = account(db, "貯蓄"), account(db, "食費", kind="expense")
    wedding = event(db, scenario, "結婚", 1_000_000, months_ahead(12))
    bonus = event(db, scenario, "臨時収入", 100_000, months_ahead(6), direction="income")
    elsewhere = event(db, other, "旅行", 1000, months_ahead(6))
    record = withdraw(db, scenario, savings.id, months_ahead(12), 600_000, wedding.id, annual_return=5.0)
    assert (record.monthly_amount_minor, record.annual_return, record.life_event_id) == (-600_000, None, wedding.id)
    for event_id in (bonus.id, elsewhere.id, 999):
        with pytest.raises(Refused):
            withdraw(db, scenario, savings.id, months_ahead(12), 1, event_id)
    with pytest.raises(Refused):
        plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": month(months_ahead(12)), "monthly_amount": 1, "life_event_id": wedding.id})
    with pytest.raises(Refused):
        withdraw(db, scenario, food.id, months_ahead(12), 1, wedding.id)
    with pytest.raises(Conflict):
        withdraw(db, scenario, savings.id, months_ahead(12), 1, wedding.id)
    # A monthly record in the same account and month stands beside it, and sets the monthly amount alone.
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": month(months_ahead(12)), "monthly_amount": 30000})
    rows = plans.list_plans(db, 1, scenario.id)
    assert plans.resolve(rows, savings.id, month(months_ahead(12)), 0.0)[0] == 30000
    assert [row.life_event_id for row in plans.withdrawals(rows)] == [wedding.id]
    # Turning it into a monthly record clears the event.
    plans.update_plan(db, 1, record.id, {"life_event_id": None, "start_period": month(months_ahead(13))})
    assert db.get(models.ScenarioContributionPlan, record.id).life_event_id is None


def test_the_simulation_moves_the_withdrawal_out_of_the_account_and_pays_the_event_from_net_worth(db):
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=1_000_000)
    securities = account(db, "証券", balance=1_000_000)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "annual_return": 0})
    trip = event(db, scenario, "旅行", 300_000, date(TODAY.year + 2, 6, 1))
    # Taken out a year before the trip, from an account that has no monthly record: it becomes a 使用口座.
    withdraw(db, scenario, securities.id, date(TODAY.year + 1, 3, 1), 200_000, trip.id)
    result = scenarios.project(db, 1, scenario)
    by_account = {row["account_id"]: row["p50"] for row in result["accounts"]}
    assert by_account[securities.id][:3] == [1_000_000, 800_000, 800_000]
    assert by_account[savings.id][:3] == [1_000_000, 1_000_000, 1_000_000]
    # Net worth moves only when the trip is paid.
    assert [row["p50"] for row in result["projection"][:3]] == [2_000_000, 2_000_000, 1_700_000]


def test_no_withdrawal_where_the_event_does_not_happen(db):
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=1_000_000)
    house = event(db, scenario, "家", 500_000, date(TODAY.year + 1, 2, 1))
    db.add(models.LifeEventCondition(client_id=1, life_event_id=house.id, metric="net_worth", comparator="gte", threshold_minor=10**12))
    db.commit()
    withdraw(db, scenario, savings.id, date(TODAY.year + 1, 6, 1), 500_000, house.id)
    result = scenarios.project(db, 1, scenario)
    assert result["accounts"][0]["p50"][:2] == [1_000_000, 1_000_000]


def test_the_plan_earmarks_each_account_until_its_withdrawal_and_draws_it_down_then(db):
    scenario = goal(db)
    savings, securities = account(db, "貯蓄", balance=500_000), account(db, "証券", balance=500_000)
    car = event(db, scenario, "車", 120_000, months_ahead(12))
    withdraw(db, scenario, savings.id, months_ahead(12), 90_000, car.id)
    withdraw(db, scenario, securities.id, months_ahead(6), 30_000, car.id)
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    assert sorted((row["kind"], row["account_id"], row["new"], row["new_capsule"]) for row in preview["changes"]) == [
        ("capsule", savings.id, 7500, True), ("capsule", securities.id, 5000, True)]
    goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])
    capsule = capsule_service.goal_capsules(db, 1, [car.id])[car.id]
    assert capsule.name == "車" and capsule.monthly_contribution_minor == 12500
    assert {(source.account_id, source.target_amount_minor) for source in capsule.funding_sources} == {(savings.id, 90000), (securities.id, 30000)}
    # In the withdrawal month the plan draws the account down for the event.
    later = goal_budget_workflow.preview(db, 1, month(months_ahead(6)), month(months_ahead(6)))
    assert ("drawdown", securities.id, 30000) in {(row["kind"], row["account_id"], row["new"]) for row in later["changes"]}

    # Money set aside in securities stays claimed there when the event stops withdrawing from it.
    create_transaction(db, client_id=1, date=TODAY, description="確保", amount_minor=1000, currency="JPY",
                       legs=[Leg(securities.id, debit=1000, capsule_id=capsule.id), Leg(securities.id, credit=1000)])
    db.commit()
    record = next(row for row in plans.list_plans(db, 1, scenario.id) if row.account_id == securities.id)
    plans.delete_plan(db, 1, record.id)
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])
    db.refresh(capsule)
    assert {(source.account_id, source.target_amount_minor) for source in capsule.funding_sources} == {(savings.id, 90000), (securities.id, 0)}


def test_a_copied_scenario_withdraws_for_the_copy_of_its_event(db):
    scenario = goal(db)
    savings = account(db, "貯蓄")
    trip = event(db, scenario, "旅行", 50_000, months_ahead(6))
    withdraw(db, scenario, savings.id, months_ahead(6), 50_000, trip.id)
    copy = scenarios.duplicate(db, 1, scenario.id, "複製")
    copied = db.query(models.LifeEvent).filter_by(scenario_id=copy.id).one()
    [record] = plans.withdrawals(plans.list_plans(db, 1, copy.id))
    assert record.life_event_id == copied.id != trip.id


def test_older_backups_turn_event_accounts_and_shares_into_withdrawal_records():
    payload = {
        "accounts": [{"id": 1, "account_type": "asset"}, {"id": 2, "account_type": "asset"}],
        "life_events": [{"id": 5, "scenario_id": 9, "direction": "expense", "target_date": "2028-10-01", "target_amount": 1000, "account_id": 1},
                        {"id": 6, "scenario_id": 9, "direction": "income", "target_date": "2027-01-01", "target_amount": 500, "account_id": 2}],
        "scenario_contribution_plans": [{"id": 3, "scenario_id": 9, "account_id": 1, "start_period": "2026-10", "monthly_amount_minor": 100}],
    }
    data = migrate_event_withdrawals(migrate_event_fundings(payload), "JPY")
    assert "life_event_fundings" not in data
    assert data["scenario_contribution_plans"][1:] == [{"id": 4, "scenario_id": 9, "account_id": 1, "start_period": "2028-10",
                                                        "monthly_amount_minor": -1000, "annual_return": None, "note": None, "life_event_id": 5}]
    shares = migrate_event_withdrawals({"life_events": payload["life_events"], "life_event_fundings": [
        {"id": 1, "life_event_id": 5, "account_id": 1, "share_bp": 7000}, {"id": 2, "life_event_id": 5, "account_id": 2, "share_bp": 3000}]}, "JPY")
    assert [(row["account_id"], row["monthly_amount_minor"]) for row in shares["scenario_contribution_plans"]] == [(1, -700), (2, -300)]


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261020_0082_event_withdrawals.py"
    spec = importlib.util.spec_from_file_location("wp22_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_turns_expense_shares_into_withdrawal_records_and_back():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_type VARCHAR)",
            "CREATE TABLE life_events (id INTEGER PRIMARY KEY, scenario_id INTEGER, direction VARCHAR, target_date DATE, target_amount_minor BIGINT)",
            "CREATE TABLE scenario_contribution_plans (id INTEGER PRIMARY KEY, scenario_id INTEGER, account_id INTEGER, start_period VARCHAR(7),"
            " monthly_amount_minor BIGINT, annual_return FLOAT, note VARCHAR,"
            " CONSTRAINT uq_scenario_contribution_plans_month UNIQUE (scenario_id, account_id, start_period))",
            "CREATE TABLE life_event_fundings (id INTEGER PRIMARY KEY, life_event_id INTEGER, account_id INTEGER, share_bp INTEGER)",
            "INSERT INTO accounts VALUES (1, 'asset'), (2, 'asset')",
            "INSERT INTO life_events VALUES (5, 9, 'expense', '2028-10-01', 1000000), (6, 9, 'income', '2027-01-01', 500)",
            "INSERT INTO scenario_contribution_plans VALUES (1, 9, 1, '2028-10', 30000, 1.0, NULL)",
            "INSERT INTO life_event_fundings VALUES (1, 5, 1, 7000), (2, 5, 2, 3000), (3, 6, 1, 10000)",
        ):
            connection.exec_driver_sql(statement)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        assert connection.exec_driver_sql(
            "SELECT scenario_id, account_id, start_period, monthly_amount_minor, life_event_id FROM scenario_contribution_plans ORDER BY id").all() == [
            (9, 1, "2028-10", 30000, None), (9, 1, "2028-10", -700000, 5), (9, 2, "2028-10", -300000, 5)]
        assert "life_event_fundings" not in sa.inspect(connection).get_table_names()
        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()
        assert connection.exec_driver_sql("SELECT life_event_id, account_id, share_bp FROM life_event_fundings ORDER BY account_id").all() == [
            (5, 1, 7000), (5, 2, 3000)]
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM scenario_contribution_plans").scalar() == 1
    engine.dispose()


@pytest.fixture
def api(db):
    app = FastAPI()
    for router in (events_router, scenarios_router):
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})
    return app


def test_http_records_a_withdrawal_and_lists_it_with_the_event(db, api):
    scenario = goal(db)
    savings = account(db, "貯蓄")
    wedding = event(db, scenario, "結婚", 1_000_000, months_ahead(12))
    created = request(api, "POST", f"/life-scenarios/{scenario.id}/contribution-plans",
                      json={"account_id": savings.id, "start_period": month(months_ahead(12)), "monthly_amount": -750000, "life_event_id": wedding.id})
    assert created.status_code == 200
    assert (created.json()["life_event_name"], created.json()["monthly_amount"]) == ("結婚", -750000)
    progress = request(api, "GET", "/life-events/with-progress").json()
    assert progress[0]["withdrawals"] == [{"account_id": savings.id, "account_name": "貯蓄", "period": month(months_ahead(12)), "amount": 750000.0}]
    assert request(api, "POST", f"/life-scenarios/{scenario.id}/contribution-plans",
                   json={"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 5, "life_event_id": wedding.id}).status_code == 422
    assert request(api, "PUT", f"/life-events/{wedding.id}/fundings", json=[]).status_code in (404, 405)
