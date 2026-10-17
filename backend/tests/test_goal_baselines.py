"""The goal baseline is frozen at adoption and measured against month-end net worth."""
import asyncio
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import DomainError, detail_for, status_for
from app.routers.goal_baselines import router
from app.services import goal_baseline_service as service
from app.services import life_scenario_service, period_close_service
from app.services.ledger_service import create_account, create_transaction
from app.workflows import goal_budget_workflow
from app.workflows.scenario_goal_workflow import choose_goal


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=1, name="本人", general_settings={"currency": "JPY"}),
                         models.Client(id=2, name="別人", general_settings={"currency": "JPY"})])
        session.add(models.SimulationConfig(client_id=1, annual_return=5, inflation_rate=2, horizon_years=10,
                                            monthly_savings_minor=50000, tax_rate=20, volatility=0))
        session.commit()
        yield session
    engine.dispose()


def deposit(db, amount, day):
    cash = db.query(models.Account).filter_by(client_id=1, name="現金").first() or create_account(db, 1, {"name": "現金", "account_type": "asset"})
    income = db.query(models.Account).filter_by(client_id=1, name="給与").first() or create_account(db, 1, {"name": "給与", "account_type": "income"})
    create_transaction(db, client_id=1, date=day, description="入金", amount_minor=amount, currency="JPY",
                       from_account_id=income.id, to_account_id=cash.id)
    db.commit()


def scenarios(db):
    goal = life_scenario_service.create(db, 1, "基本")
    other = life_scenario_service.create(db, 1, "別案")
    return goal, other


def test_choosing_a_goal_freezes_its_baseline_and_keeps_history(db):
    goal, other = scenarios(db)
    choose_goal(db, 1, goal.id)
    first = service.current(db, 1)
    assert (first.scenario_id, first.reason, first.is_current) == (goal.id, "adopted", True)
    assert first.projection[0]["offset"] == 0 and len(first.projection) == goal.horizon_years + 1
    # Editing the goal afterwards never moves the frozen projection.
    frozen = list(first.projection)
    life_scenario_service.update(db, 1, goal.id, {"monthly_savings": 900000})
    assert service.current(db, 1).projection == frozen
    # Choosing the same goal again adds nothing; another goal replaces the current one.
    choose_goal(db, 1, goal.id)
    assert db.query(models.GoalBaseline).count() == 1
    choose_goal(db, 1, other.id)
    rows = service.history(db, 1)
    assert [(row["scenario_name"], row["is_current"]) for row in rows] == [("別案", True), ("基本", False)]


def test_comparison_reports_month_end_actuals_closed_or_provisional(db):
    goal, _ = scenarios(db)
    deposit(db, 1_000_000, date(2026, 1, 10))
    life_scenario_service.make_goal(db, 1, goal.id)
    baseline = service.capture(db, 1, "manual", today=date(2026, 1, 15))
    baseline.projection = [{"offset": 0, "year": 2026, "p10": 900_000, "p50": 1_000_000, "p90": 1_100_000},
                           {"offset": 1, "year": 2027, "p10": 1_500_000, "p50": 2_200_000, "p90": 2_900_000}]
    db.commit()
    deposit(db, 50_000, date(2026, 2, 20))
    period_close_service.close_period(db, 1, "2026-01")
    result = service.comparison(db, 1, today=date(2026, 3, 10))
    rows = {row["period"]: row for row in result["rows"]}
    assert len(result["rows"]) == 13  # at least a year of band, from the anchor month
    assert (rows["2026-01"]["actual"], rows["2026-01"]["closed"]) == (1_000_000, True)
    assert (rows["2026-02"]["actual"], rows["2026-02"]["closed"]) == (1_050_000, False)
    # The current month is valued today and compared with the band at today.
    assert rows["2026-03"]["date"] == "2026-03-10" and rows["2026-03"]["actual"] == 1_050_000
    assert rows["2026-04"]["actual"] is None
    expected = 1_000_000 + 1_200_000 * (date(2026, 3, 10) - date(2026, 1, 15)).days / 365.25
    assert rows["2026-03"]["p50"] == pytest.approx(expected)
    latest = result["latest"]
    assert latest["period"] == "2026-03" and latest["difference"] == pytest.approx(1_050_000 - expected)
    assert latest["below_p10"] is False and latest["closed"] is False


def test_comparison_flags_falling_below_the_cautious_band(db):
    goal, _ = scenarios(db)
    life_scenario_service.make_goal(db, 1, goal.id)
    baseline = service.capture(db, 1, "manual", today=date(2026, 1, 15))
    baseline.projection = [{"offset": 0, "year": 2026, "p10": 100, "p50": 200, "p90": 300},
                           {"offset": 1, "year": 2027, "p10": 100, "p50": 200, "p90": 300}]
    db.commit()
    assert service.comparison(db, 1, today=date(2026, 2, 1))["latest"]["below_p10"] is True


def test_reflection_records_allocations_and_may_update_the_baseline(db):
    goal, _ = scenarios(db)
    choose_goal(db, 1, goal.id)
    db.add_all([
        models.LifeEvent(client_id=1, scenario_id=goal.id, name="遠い", target_date=date(2046, 11, 1),
                         target_amount_minor=1_000_000, priority=1),
        models.LifeEvent(client_id=1, scenario_id=goal.id, name="遠い2", target_date=date(2047, 11, 1),
                         target_amount_minor=1_000_000, priority=3),
    ])
    db.commit()
    options = {"savings_source": "scenario", "near_years": 5, "start_period": "2026-11", "months": 1,
               "savings_account_id": None, "savings_definition_id": None, "uncounted": [], "create_capsules": []}
    preview = goal_budget_workflow.preview(db, 1, options)
    # Far events share everything saved by priority (3:1).
    assert {row["name"]: row["allocation"] for row in preview["events"]} == {"遠い": 37500, "遠い2": 12500}
    goal_budget_workflow.apply(db, 1, options, preview["fingerprint"], update_baseline=True)
    record = db.query(models.GoalBudgetReflection).one()
    assert (record.scenario_id, record.start_period, record.end_period) == (goal.id, "2026-11", "2026-11")
    assert sorted(row["allocation"] for row in record.events) == [12500, 37500]
    assert service.current(db, 1).reason == "reflection"
    assert db.query(models.GoalBaseline).count() == 2


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})
    return app


def request(app, method, url, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.request(method, url, **kwargs))
            for _ in range(3000):
                if pending.done():
                    return await pending
                await asyncio.sleep(.01)
            pending.cancel()
            pytest.fail("HTTP baseline request timed out")
    return asyncio.run(run())


def test_http_capture_and_read(db, api):
    assert request(api, "POST", "/goal-baselines").status_code == 422  # no goal yet
    assert request(api, "GET", "/goal-baselines/current").json() == {"baseline": None, "rows": [], "latest": None}
    goal, _ = scenarios(db)
    life_scenario_service.make_goal(db, 1, goal.id)
    captured = request(api, "POST", "/goal-baselines")
    assert captured.status_code == 200 and captured.json()["baseline"]["reason"] == "manual"
    assert request(api, "GET", "/goal-baselines/current").json()["baseline"]["scenario_name"] == "基本"
    assert [row["reason"] for row in request(api, "GET", "/goal-baselines").json()] == ["manual"]



def far_story(db):
    goal, other = scenarios(db)
    life_scenario_service.make_goal(db, 1, goal.id)
    rows = {
        "near": models.LifeEvent(client_id=1, scenario_id=goal.id, lineage="near", name="近い", priority=2,
                                 target_date=date(date.today().year + 2, date.today().month, 1), target_amount_minor=240_000),
        "far1": models.LifeEvent(client_id=1, scenario_id=goal.id, lineage="far1", name="遠い", priority=1,
                                 target_date=date(2050, 1, 1), target_amount_minor=1_000_000),
        "far3": models.LifeEvent(client_id=1, scenario_id=goal.id, lineage="far3", name="遠い2", priority=3,
                                 target_date=date(2051, 1, 1), target_amount_minor=1_000_000),
        "idea": models.LifeEvent(client_id=1, scenario_id=goal.id, lineage="idea", name="案", priority=1,
                                 target_date=date(2050, 1, 1), target_amount_minor=1_000_000,
                                 budget_reflection="simulation_only"),
    }
    db.add_all(rows.values())
    db.commit()
    return goal, rows


def test_event_progress_divides_savings_like_the_reflection(db):
    from app.services.strategy_service import get_goal_simulation_context, get_life_events_with_progress
    _, rows = far_story(db)
    allocation = {name: get_goal_simulation_context(db, 1, row)["allocated_monthly_savings"] for name, row in rows.items()}
    # Near: shortfall over the 24 months left; far: a 3:1 priority share of the rest;
    # simulation only: nothing.
    assert allocation["near"] == pytest.approx(10_000)
    assert allocation["far1"] == pytest.approx(40_000 * 3 / 4)
    assert allocation["far3"] == pytest.approx(40_000 / 4)
    assert allocation["idea"] == 0
    progress = {row["name"]: row for row in get_life_events_with_progress(db, 1)}
    assert progress["近い"]["monthly_allocation"] == pytest.approx(10_000)
    assert progress["近い"]["allocation_source"] == "rule"


def test_an_applied_reflection_is_what_progress_reads(db):
    from app.services.strategy_service import get_goal_simulation_context
    goal, rows = far_story(db)
    month = date.today().strftime("%Y-%m")
    db.add(models.GoalBudgetReflection(client_id=1, scenario_id=goal.id, start_period=month, end_period=month,
                                       options={"near_years": 5}, summary={}, events=[
                                           {"lineage": "near", "allocation": 12_345}, {"lineage": "far1", "allocation": 1_000}]))
    db.commit()
    context = get_goal_simulation_context(db, 1, rows["near"])
    assert (context["allocated_monthly_savings"], context["allocation_source"]) == (12_345, "reflection")
    # An event the reflection did not know falls back to the rule.
    assert get_goal_simulation_context(db, 1, rows["far3"])["allocation_source"] == "rule"
    # A what-if amount is divided by the rule, not read from the budget.
    what_if = get_goal_simulation_context(db, 1, rows["near"], monthly_savings=999_999)
    assert what_if["allocation_source"] == "rule" and what_if["allocated_monthly_savings"] == pytest.approx(10_000)


def test_near_events_share_savings_that_cannot_cover_them(db):
    from app.services.strategy_service import get_goal_simulation_context
    _, rows = far_story(db)
    life_scenario_service.update(db, 1, rows["near"].scenario_id, {"monthly_savings": 4_000})
    assert get_goal_simulation_context(db, 1, rows["near"])["allocated_monthly_savings"] == pytest.approx(4_000)
    assert get_goal_simulation_context(db, 1, rows["far1"])["allocated_monthly_savings"] == 0
