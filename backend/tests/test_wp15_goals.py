"""WP15: contribution plans, goal earmarks, the account-by-account simulation and the plan made from the goal."""
from datetime import date
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import models
from app.database import get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, NotFound, Refused, detail_for, status_for
from app.domain.journal import Leg
from app.domain.transfer import migrate_goal_fields
from app.routers.goal_budget import router as goal_budget_router
from app.routers.life_events import router as events_router
from app.routers.life_scenarios import router as scenarios_router
from app.services import capsule_service
from app.services import contribution_plan_service as plans
from app.services import goal_plan_service, life_event_graph, life_scenario_service as scenarios
from app.services.ledger_service import create_transaction
from app.workflows import goal_budget_workflow
from scenario_fixtures import account, db, request  # noqa: F401

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")


def in_years(years: int, month: int | None = None) -> date:
    return date(TODAY.year + years, month or TODAY.month, 1)


def months_ahead(months: int) -> date:
    index = TODAY.year * 12 + TODAY.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def goal(db, name="ゴール", **values):
    scenario = models.LifeScenario(client_id=1, name=name, is_goal=True, annual_return=0, inflation=0, horizon_years=3, **values)
    db.add(scenario)
    db.commit()
    return scenario


def event(db, scenario, name, amount, when, direction="expense", account_id=None):
    row = models.LifeEvent(client_id=1, scenario_id=scenario.id, name=name, target_amount_minor=amount,
                           target_date=when, direction=direction, account_id=account_id)
    db.add(row)
    db.commit()
    return row


def earmark(db, name, funding_account, target=0):
    capsule = models.Capsule(client_id=1, name=name, target_amount_minor=target, monthly_contribution_minor=0,
                             funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=funding_account.id,
                                                                          target_amount_minor=target or 1)])
    db.add(capsule)
    db.commit()
    return capsule


def still(db):
    """No market noise, no tax: the simulation becomes arithmetic."""
    db.add(models.SimulationConfig(client_id=1, volatility=0, tax_rate=0))
    db.commit()


def test_contribution_plan_records_replace_amounts_and_carry_yields_forward():
    rows = [SimpleNamespace(account_id=1, start_period="2026-01", monthly_amount_minor=10000, annual_return=3.0),
            SimpleNamespace(account_id=1, start_period="2029-04", monthly_amount_minor=50000, annual_return=None),
            SimpleNamespace(account_id=1, start_period="2031-01", monthly_amount_minor=0, annual_return=1.0),
            SimpleNamespace(account_id=2, start_period="2026-01", monthly_amount_minor=7000, annual_return=None)]
    assert plans.resolve(rows, 1, "2025-12", 5.0) == (0, 5.0)
    assert plans.resolve(rows, 1, "2029-03", 5.0) == (10000, 3.0)
    assert plans.resolve(rows, 1, "2029-04", 5.0) == (50000, 3.0)
    assert plans.resolve(rows, 1, "2031-06", 5.0) == (0, 1.0)
    assert plans.resolve(rows, 2, "2030-01", 5.0) == (7000, 5.0)
    assert plans.monthly_total_minor(rows, "2029-04") == 57000


def test_contribution_plans_validate_account_period_and_uniqueness(db):
    scenario = goal(db)
    savings, food = account(db, "貯蓄"), account(db, "食費", kind="expense")
    plan = plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 30000})
    assert plans.serialize(db, 1, plan)["monthly_amount"] == 30000
    with pytest.raises(Conflict):
        plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD})
    with pytest.raises(Refused):
        plans.create_plan(db, 1, scenario.id, {"account_id": food.id, "start_period": PERIOD})
    with pytest.raises(Refused):
        plans.update_plan(db, 1, plan.id, {"start_period": "2026-13"})
    with pytest.raises(NotFound):
        plans.update_plan(db, 2, plan.id, {"monthly_amount": 1})
    plans.update_plan(db, 1, plan.id, {"annual_return": None, "monthly_amount": 40000})
    assert (plan.monthly_amount_minor, plan.annual_return) == (40000, None)


def test_duplicating_copies_the_story_and_contributions_not_earmarks_and_goal_only_flags(db):
    original = goal(db)
    savings = account(db, "貯蓄")
    first, second = event(db, original, "A", 1000, in_years(1)), event(db, original, "B", 2000, in_years(2))
    life_event_graph.create_link(db, 1, from_event_id=first.id, to_event_id=second.id, kind="after", offset_months=6)
    db.add(models.LifeEventCondition(client_id=1, life_event_id=second.id, metric="net_worth", comparator="gte", threshold_minor=10))
    plans.create_plan(db, 1, original.id, {"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 5000})
    capsule = capsule_service.create_goal_capsule(db, 1, event_id=first.id, name="A", target_minor=1000, account_id=savings.id)
    db.commit()

    copy = scenarios.duplicate(db, 1, original.id, "複製")
    copied = db.query(models.LifeEvent).filter_by(scenario_id=copy.id).order_by(models.LifeEvent.id).all()
    assert [row.name for row in copied] == ["A", "B"] and {row.lineage for row in copied} == {first.lineage, second.lineage}
    assert db.query(models.LifeEventLink).filter(models.LifeEventLink.from_event_id == copied[0].id).one().offset_months == 6
    assert db.query(models.LifeEventCondition).filter_by(life_event_id=copied[1].id).count() == 1
    assert [(row.account_id, row.monthly_amount_minor) for row in db.query(models.ScenarioContributionPlan).filter_by(scenario_id=copy.id)] == [(savings.id, 5000)]
    # A copied story makes no earmarks: they belong to the goal, not to the story.
    assert db.query(models.Capsule).filter(models.Capsule.goal_event_id.in_([row.id for row in copied])).count() == 0

    scenarios.make_goal(db, 1, copy.id)
    assert (db.get(models.LifeScenario, copy.id).is_goal, db.get(models.LifeScenario, original.id).is_goal) == (True, False)
    # Marking the goal alone moves no earmark.
    assert db.get(models.Capsule, capsule.id).goal_event_id == first.id


def test_simulation_runs_events_only_where_their_branch_and_preconditions_hold(db):
    still(db)
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=100000)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 10000, "annual_return": 0})
    car = event(db, scenario, "車", 50000, in_years(1), account_id=savings.id)
    house = event(db, scenario, "家", 1000000, in_years(2))
    furniture = event(db, scenario, "家具", 10000, in_years(2))
    db.add(models.LifeEventCondition(client_id=1, life_event_id=house.id, metric="net_worth", comparator="gte", threshold_minor=10_000_000))
    db.commit()
    life_event_graph.create_link(db, 1, from_event_id=house.id, to_event_id=furniture.id, kind="after")

    result = scenarios.project(db, 1, scenario)
    assert [row["p50"] for row in result["projection"]] == [100000, 170000, 290000, 410000]
    by_id = {row["id"]: row for row in result["events"]}
    assert (by_id[car.id]["executed_probability"], by_id[car.id]["funded_probability"]) == (1.0, 1.0)
    assert by_id[house.id]["executed_probability"] == by_id[furniture.id]["executed_probability"] == 0.0
    assert result["likely_path"] == {"event_ids": [car.id], "link_ids": []}
    assert [row["probability"] for row in result["conditions"] if row["event_id"] == house.id] == [0.0]
    assert result["accounts"][0]["p50"][:3] == [100000, 170000, 290000]
    assert result["monthly_contribution"] == 10000
    # The chart's demand lines still count every event, happened or not.
    assert result["projection"][2]["cumulative_target"] == 1060000


def test_a_branch_most_paths_take_reports_its_link(db):
    still(db)
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=5_000_000)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "annual_return": 0})
    parent = event(db, scenario, "転職", 0, in_years(1))
    child = event(db, scenario, "引越し", 300000, in_years(2), account_id=savings.id)
    link = life_event_graph.create_link(db, 1, from_event_id=parent.id, to_event_id=child.id, kind="after")
    result = scenarios.project(db, 1, scenario)
    assert result["likely_path"] == {"event_ids": sorted([parent.id, child.id]), "link_ids": [link.id]}
    assert result["accounts"][0]["p50"][2] == 4_700_000


def plan_setup(db):
    """A goal with a 30000 monthly contribution to savings and one event set aside there."""
    scenario = goal(db)
    savings = account(db, "貯蓄")
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 30000})
    appliance = event(db, scenario, "家電の買い替え", 120000, months_ahead(12), account_id=savings.id)
    return scenario, savings, appliance


def test_the_plan_takes_earmarks_out_of_the_account_contribution_and_applies_once(db):
    scenario, savings, appliance = plan_setup(db)
    assert goal_plan_service.reflection_notifications(db, 1, PERIOD)[0]["dedupe_key"] == f"goal_reflection:{scenario.id}:{PERIOD}"
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    assert {(row["kind"], row["new"]) for row in preview["changes"]} == {("capsule", 10000), ("account", 20000)}
    made = next(row for row in preview["changes"] if row["kind"] == "capsule")
    assert (made["new_capsule"], made["capsule_name"], made["event_id"]) == (True, "家電の買い替え", appliance.id)
    assert preview["warnings"] == []
    with pytest.raises(Conflict):
        goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, "0" * 64)
    assert goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])["applied"] == 2
    # Applying made the event's earmark, named after it, in its account.
    capsule = db.query(models.Capsule).filter_by(goal_event_id=appliance.id).one()
    assert (capsule.name, capsule.target_amount_minor, capsule.monthly_contribution_minor, [source.account_id for source in capsule.funding_sources]) == (
        "家電の買い替え", 120000, 10000, [savings.id])
    rows = db.query(models.MonthlyPlanLine).filter_by(client_id=1, is_active=True, source_kind="goal").all()
    assert {(row.target_type, row.target_id if row.target_type == "capsule" else None, row.account_id, row.amount_minor) for row in rows} == {
        ("capsule", capsule.id, savings.id, 10000), ("account", None, savings.id, 20000)}
    again = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    assert not any(row["changed"] for row in again["changes"])
    check = goal_plan_service.plan_check(db, 1, PERIOD)
    assert (check["contribution"], check["planned"], check["difference"], check["reflected"]) == (30000, 30000, 0, True)
    assert goal_plan_service.reflection_notifications(db, 1, PERIOD) == []
    assert db.query(models.GoalBudgetReflection).one().scenario_id == scenario.id


def test_the_plan_warns_when_earmarks_exceed_the_contribution(db):
    scenario, savings, appliance = plan_setup(db)
    plan_row = plans.list_plans(db, 1, scenario.id)[0]
    plans.update_plan(db, 1, plan_row.id, {"monthly_amount": 4000})
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    # An account left with nothing after its earmarks gets no row written.
    assert {(row["kind"], row["new"]) for row in preview["changes"]} == {("capsule", 10000)}
    assert preview["warnings"] and "超えています" in preview["warnings"][0]
    # The same shortfall over several months is one warning naming them.
    longer = goal_budget_workflow.preview(db, 1, PERIOD, months_ahead(2).strftime("%Y-%m"))
    assert len(longer["warnings"]) == 1 and "のうち3か月" in longer["warnings"][0]
    # Later months share the remaining need equally: 120000 over 12 months is 10000 each.
    assert {row["new"] for row in longer["changes"] if row["kind"] == "capsule"} == {10000}
    with pytest.raises(Refused):
        goal_budget_workflow.preview(db, 1, PERIOD, "1999-01")


def test_the_plan_counts_what_the_account_already_receives_and_keeps_those_rows(db):
    from app.services.budget_plan_store import create_plan_lines, resolve_budget_plan_id
    scenario, savings, appliance = plan_setup(db)
    plan_id = resolve_budget_plan_id(db, 1)
    # A transfer the user planned by hand already covers part of the contribution.
    manual = create_plan_lines(db, 1, [{"plan_id": plan_id, "target_period": PERIOD, "line_type": "allocation", "target_type": "account",
                                        "account_id": savings.id, "amount": 15000, "source": "manual", "source_kind": "manual"}])[0]
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    assert {(row["kind"], row["new"]) for row in preview["changes"]} == {("capsule", 10000), ("account", 5000)}
    goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])
    db.refresh(manual)
    assert manual.is_active and manual.amount_minor == 15000
    check = goal_plan_service.plan_check(db, 1, PERIOD)
    assert (check["contribution"], check["planned"], check["difference"]) == (30000, 30000, 0)


def test_backup_upgrade_moves_yields_and_event_capsules_like_the_migration():
    old = {
        "life_scenarios": [{"id": 1, "name": "基本", "monthly_savings": 50000, "is_goal": True}],
        "life_scenario_account_returns": [{"id": 9, "scenario_id": 1, "account_id": 3, "annual_return": 4.0}],
        "life_events": [{"id": 5, "scenario_id": 1, "name": "家", "start_date": "2026-01-01", "budget_reflection": "firm", "archived_at": None},
                        {"id": 6, "scenario_id": 1, "name": "中止", "archived_at": "2026-02-01T00:00:00"}],
        "life_event_links": [{"id": 1, "from_event_id": 5, "to_event_id": 6}],
        "life_event_conditions": [{"id": 1, "life_event_id": 6}],
        "capsules": [{"id": 7, "life_event_id": 5, "capsule_type": "life_event", "target_amount_source": "life_event"},
                     {"id": 8, "life_event_id": 6}],
        "monthly_plan_lines": [{"id": 1, "target_type": "life_event", "target_id": 5, "is_active": True},
                               {"id": 2, "target_type": "life_event", "target_id": 6, "is_active": True}],
        "milestones": [{"id": 1}], "goal_baselines": [{"id": 1}], "simulation_scenarios": [{"id": 1}],
        "goal_budget_reflections": [{"id": 1, "options": {}, "events": [], "summary": {"x": 1}}],
    }
    data = migrate_goal_fields(old, "2026-10")
    assert data["scenario_contribution_plans"] == [{"id": 1, "scenario_id": 1, "account_id": 3, "start_period": "2026-10",
                                                    "monthly_amount_minor": 0, "annual_return": 4.0, "note": None}]
    assert data["goal_event_earmarks"] == [{"id": 1, "life_event_id": 5, "capsule_id": 7, "share_bp": 10000}]
    assert [row["id"] for row in data["life_events"]] == [5] and "start_date" not in data["life_events"][0]
    assert data["life_event_links"] == [] and data["life_event_conditions"] == []
    assert data["capsules"][0] == {"id": 7, "capsule_type": "manual", "target_amount_source": "manual"}
    assert [(row["target_type"], row["target_id"], row["is_active"]) for row in data["monthly_plan_lines"]] == [
        ("capsule", 7, True), ("life_event", 6, False)]
    assert not {"milestones", "goal_baselines", "simulation_scenarios", "life_scenario_account_returns"} & data.keys()
    assert data["goal_budget_reflections"] == [{"id": 1, "summary": {"x": 1}}] and "monthly_savings" not in data["life_scenarios"][0]
    assert old["capsules"][0]["life_event_id"] == 5  # the verified payload itself is left untouched


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261019_0078_goal_redesign.py"
    spec = importlib.util.spec_from_file_location("wp15_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_adds_beside_the_old_data_and_detaches_event_capsules():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE clients (id INTEGER PRIMARY KEY)",
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, client_id INTEGER)",
            "CREATE TABLE life_scenarios (id INTEGER PRIMARY KEY, client_id INTEGER)",
            "CREATE TABLE life_events (id INTEGER PRIMARY KEY, client_id INTEGER, scenario_id INTEGER)",
            "CREATE TABLE capsules (id INTEGER PRIMARY KEY, client_id INTEGER, life_event_id INTEGER REFERENCES life_events(id) ON DELETE CASCADE)",
            "CREATE TABLE milestones (id INTEGER PRIMARY KEY, life_event_id INTEGER)",
            "CREATE TABLE life_scenario_account_returns (id INTEGER PRIMARY KEY, scenario_id INTEGER, account_id INTEGER, annual_return FLOAT)",
            "CREATE TABLE goal_budget_reflections (id INTEGER PRIMARY KEY, client_id INTEGER, options JSON NOT NULL, events JSON NOT NULL, summary JSON NOT NULL)",
            "INSERT INTO clients VALUES (1)", "INSERT INTO accounts VALUES (3, 1)", "INSERT INTO life_scenarios VALUES (2, 1)",
            "INSERT INTO life_events VALUES (5, 1, 2)", "INSERT INTO capsules VALUES (7, 1, 5), (8, 1, NULL)",
            "INSERT INTO milestones VALUES (1, 5)", "INSERT INTO life_scenario_account_returns VALUES (1, 2, 3, 4.5)",
        ):
            connection.exec_driver_sql(statement)
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        assert connection.exec_driver_sql("SELECT scenario_id, account_id, monthly_amount_minor, annual_return FROM scenario_contribution_plans").all() == [(2, 3, 0, 4.5)]
        assert connection.exec_driver_sql("SELECT client_id, life_event_id, capsule_id, share_bp FROM goal_event_earmarks").all() == [(1, 5, 7, 10000)]
        assert connection.exec_driver_sql("SELECT id, life_event_id FROM capsules ORDER BY id").all() == [(7, None), (8, None)]
        # Nothing old is dropped: retired tables keep their rows until an approved migration removes them.
        assert connection.exec_driver_sql("SELECT count(*) FROM milestones").scalar() == 1
        assert connection.exec_driver_sql("SELECT count(*) FROM life_scenario_account_returns").scalar() == 1
        connection.exec_driver_sql("INSERT INTO goal_budget_reflections (id, client_id, summary) VALUES (1, 1, '{}')")
        with Operations.context(MigrationContext.configure(connection)):
            connection.exec_driver_sql("DELETE FROM goal_budget_reflections")
            migration().downgrade()
        assert connection.exec_driver_sql("SELECT id, life_event_id FROM capsules ORDER BY id").all() == [(7, 5), (8, None)]
        assert "goal_event_earmarks" not in sa.inspect(connection).get_table_names()
    engine.dispose()


@pytest.fixture
def api(db):
    app = FastAPI()
    for router in (events_router, scenarios_router, goal_budget_router):
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})
    return app


def test_http_conditions_contribution_plans_earmarks_and_plan_check(db, api):
    scenario = goal(db)
    savings = account(db, "貯蓄")
    house = event(db, scenario, "家", 1000, in_years(2), account_id=savings.id)
    capsule = capsule_service.create_goal_capsule(db, 1, event_id=house.id, name="家", target_minor=1000, account_id=savings.id)
    db.commit()
    created = request(api, "POST", f"/life-events/{house.id}/conditions", json={"metric": "net_worth", "comparator": "gte", "threshold_minor": 100})
    updated = request(api, "PUT", f"/life-events/{house.id}/conditions/{created.json()['id']}",
                      json={"metric": "net_worth", "comparator": "lte", "threshold_minor": 50, "note": "上限"})
    assert (updated.status_code, updated.json()["comparator"], updated.json()["threshold_minor"]) == (200, "lte", 50)
    record = request(api, "POST", f"/life-scenarios/{scenario.id}/contribution-plans",
                     json={"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 20000, "annual_return": 1.5})
    assert record.status_code == 200 and record.json()["account_name"] == "貯蓄"
    assert request(api, "PUT", f"/life-scenarios/contribution-plans/{record.json()['id']}", json={"monthly_amount": 25000}).json()["monthly_amount"] == 25000
    assert [row["monthly_amount"] for row in request(api, "GET", f"/life-scenarios/{scenario.id}/contribution-plans").json()] == [25000]
    progress = request(api, "GET", "/life-events/with-progress").json()
    assert progress[0]["earmark"] == {"capsule_id": capsule.id, "capsule_name": "家"}
    check = request(api, "GET", f"/goal-budget/plan-check?period={PERIOD}").json()
    assert (check["contribution"], check["planned"], check["reflected"]) == (25000, 0, False)
    assert request(api, "DELETE", f"/life-scenarios/contribution-plans/{record.json()['id']}").status_code == 200
    assert request(api, "DELETE", f"/life-events/{house.id}").status_code == 200
    # The earmark outlives its event; it simply stops belonging to the goal.
    db.expire_all()
    assert db.get(models.Capsule, capsule.id).goal_event_id is None
