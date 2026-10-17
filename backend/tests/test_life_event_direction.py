"""Receipts affect projections, never the amount a client must save."""
import asyncio
import json
from datetime import date, datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import DomainError, NotFound, Refused, detail_for, status_for
from app.domain.transfer import EXPORT_VERSION, validate_import_payload
from app.routers import ai, life_events, simulation
from app.services import (
    ai_context_service, analysis_service, capsule_service, goal_service,
    ledger_service, life_event_conditions, life_event_graph, milestone_service,
    report_service, simulation_scenario_service, strategy_service,
)
from app.services.data_transfer_service import export_client, import_client
from app.workflows.goal_workflow import create_goal
from app.workflows.simulation_workflow import monte_carlo_for_goal
from app.workflows import capsule_workflow, monthly_action_workflow


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add_all([models.Client(id=i, name=f"本人{i}", general_settings={"currency": "JPY"}) for i in (1, 2)])
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(life_events.router)
    app.include_router(simulation.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})

    return app


def request(api, method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
            pending = asyncio.create_task(client.request(method, path, **kwargs))
            # Timer wakeups keep the sandbox's worker-thread completions moving.
            deadline = asyncio.get_running_loop().time() + 10
            while not pending.done() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
            assert pending.done(), "HTTP request exceeded 10 seconds"
            return await pending

    return asyncio.run(run())


def account(db, client_id=1):
    row = models.Account(client_id=client_id, name=f"口座{client_id}", account_type="asset")
    db.add(row)
    db.commit()
    return row


def node(db, direction="expense", amount=1200, offset=2, **kwargs):
    row = models.LifeEvent(client_id=1, name=direction, direction=direction,
                           target_date=date(date.today().year + offset, 1, 1),
                           target_amount_minor=amount, **kwargs)
    db.add(row)
    db.commit()
    return row


def reserve(db, owner):
    """Keep pre-conversion claims and milestones to detect accidental funding reads."""
    cash = account(db)
    income = models.Account(client_id=1, name="給与", account_type="income")
    cap = models.Capsule(client_id=1, life_event_id=owner.id, name="保存済み", target_amount_minor=1200)
    db.add_all([income, cap])
    db.flush()
    ledger_service.create_transaction(db, client_id=1, date=date.today(), amount_minor=600,
        currency="JPY", description="確保済み", legs=[
            ledger_service.Leg(cash.id, debit=600, capsule_id=cap.id),
            ledger_service.Leg(income.id, credit=600),
        ])
    db.add(models.Milestone(client_id=1, life_event_id=owner.id, date=date.today(), target_amount_minor=1000))
    db.commit()
    return cap


def test_http_income_create_update_and_all_event_serializers_round_trip(db, api):
    linked = account(db)
    payload = {"name": "退職金", "target_date": "2040-03-31", "target_amount": 2000,
               "direction": "income", "account_id": linked.id}
    response = request(api, "POST", "/life-events/", json=payload)
    assert response.status_code == 200
    event_id = response.json()["id"]
    assert (response.json()["direction"], response.json()["account_id"]) == ("income", linked.id)
    assert request(api, "PUT", f"/life-events/{event_id}", json={"note": "更新"}).json()["direction"] == "income"
    for path in ("/life-events/", "/life-events/with-progress", "/life-events/dashboard"):
        result = request(api, "GET", path).json()
        row = (result["events"] if isinstance(result, dict) else result)[0]
        assert (row["direction"], row["account_id"]) == ("income", linked.id)
    assert request(api, "PUT", f"/life-events/{event_id}", json={"direction": "expense", "account_id": None}).json()["account_id"] is None
    changed = request(api, "PUT", f"/life-events/{event_id}", json={"direction": "income", "account_id": linked.id})
    assert changed.json()["direction"] == "income" and changed.json()["account_id"] == linked.id
    context = ai_context_service._goals(db, 1, 10)["goals"][0]
    assert context["direction"] == "income" and context["account_id"] == linked.id


@pytest.mark.parametrize("missing", [False, True])
def test_account_ownership_refused_on_create_and_update_before_any_mutation(db, api, missing):
    foreign_id = 9999 if missing else account(db, 2).id
    expense = node(db)
    payload = {"name": "相続", "target_date": "2040-01-01", "target_amount": 100,
               "direction": "income", "account_id": foreign_id}
    assert request(api, "POST", "/life-events/", json=payload).status_code == 404
    assert request(api, "PUT", f"/life-events/{expense.id}", json={"name": "変更", "account_id": foreign_id}).status_code == 404
    with pytest.raises(NotFound):
        goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(**payload))
    db.expire_all()
    assert expense.name == "expense" and db.query(models.LifeEvent).count() == 1


@pytest.mark.parametrize("direction", [None, "other"])
def test_direction_is_validated_for_create_and_update(db, api, direction):
    expense = node(db)
    payload = {"name": "イベント", "target_date": "2040-01-01", "target_amount": 100, "direction": direction}
    assert request(api, "POST", "/life-events/", json=payload).status_code == 422
    assert request(api, "PUT", f"/life-events/{expense.id}", json={"direction": direction}).status_code == 422


def test_deleting_linked_account_sets_event_reference_to_null(db):
    linked = account(db)
    receipt = node(db, "income", account_id=linked.id)
    # API deletion deactivates accounts; a physical deletion exercises SET NULL.
    db.delete(linked)
    db.commit()
    db.expire_all()
    assert receipt.account_id is None and receipt.direction == "income"


@pytest.mark.parametrize("commit", [False, True])
def test_income_goal_workflow_creates_no_capsule_or_milestone(db, commit):
    receipt = create_goal(db, 1, schemas.LifeEventCreate(
        name="相続", target_date=date(2040, 1, 1), target_amount=500, direction="income"), commit=commit)
    assert receipt.direction == "income"
    assert db.query(models.Capsule).count() == db.query(models.Milestone).count() == 0
    if not commit:
        db.rollback()
        assert db.query(models.LifeEvent).count() == 0


def test_income_is_excluded_from_savings_allocation_and_priority_denominator(db):
    expense = node(db, priority=3)
    receipt = node(db, "income", priority=1)
    for mode in ("weighted", "direct"):
        assert strategy_service.get_goal_simulation_context(db, 1, expense, monthly_savings=120, allocation_mode=mode)["allocated_monthly_savings"] == 120
        assert strategy_service.get_goal_simulation_context(db, 1, receipt, monthly_savings=120, allocation_mode=mode)["allocated_monthly_savings"] == 0


def test_income_ignores_saved_claims_in_current_funding(db):
    receipt = node(db, "income")
    cap = reserve(db, receipt)
    assert capsule_service.capsule_balance(db, cap) == 600
    assert strategy_service.calculate_current_funded(receipt, db) == 0
    assert strategy_service.calculate_current_funded_and_weighted_return(receipt, db) == (0, 5)


def test_income_has_no_funded_percentage_shortfall_or_savings_status(db):
    receipt = node(db, "income")
    reserve(db, receipt)
    row = strategy_service.get_life_events_with_progress(db, 1)[0]
    assert row["target_amount"] == 1200 and row["direction"] == "income"
    assert row["current_funded"] == row["funded_percentage"] == row["progress_percentage"] == row["gap"] == 0
    assert row["status"] == "Not Applicable" and row["roadmap"] == []


def test_income_has_no_plan_status_even_with_saved_plan_and_override(db):
    receipt = node(db, "income", plan_status_override="Behind")
    reserve(db, receipt)
    plan = strategy_service.calculate_milestone_plan_progress(receipt, 600, date.today())
    assert plan["plan_status"] == "No Plan" and plan["plan_gap"] == plan["plan_progress_percentage"] == 0
    assert plan["plan_previous_milestone"] is plan["plan_next_milestone"] is None


def test_overall_probability_excludes_income_targets_and_counts(db):
    expense = node(db)
    node(db, "income", amount=999999)
    result = strategy_service.calculate_overall_goal_probability(db, 1)
    assert result["total_goals"] == 1 and result["total_target"] == 1200
    assert [row["id"] for row in result["goals"]] == [expense.id]


def test_income_is_excluded_from_roadmap_progression():
    assert strategy_service.calculate_roadmap_progression([
        {"direction": "income", "target_amount": 999999, "progress_percentage": 0},
        {"direction": "expense", "target_amount": 1200, "progress_percentage": 100},
    ]) == {"progression": 100, "status": "On Track"}


def test_income_is_excluded_from_generated_savings_budget(db):
    node(db, priority=3)
    node(db, "income", priority=1)
    budget = strategy_service.generate_budget_from_goals(db, "2026-10", 1)
    assert len(budget) == 1 and budget[0]["derived_from"] == "expense"
    assert budget[0]["proposed_amount"] == 100000


def test_income_is_excluded_from_funding_gap_and_required_monthly_savings(db):
    node(db)
    baseline = strategy_service.summarize_goal_funding_gap(db, 1)
    node(db, "income", amount=999999)
    assert strategy_service.summarize_goal_funding_gap(db, 1) == baseline
    assert baseline["goals_count"] == 1


def test_income_is_excluded_from_analysis_goal_count_and_progression(db):
    node(db, "income")
    summary = analysis_service.get_summary(db, 1)
    assert summary["total_goal_count"] == 0
    assert summary["roadmap_progression"] == "On Track"


def test_net_position_excludes_income_from_future_funding_costs(db):
    node(db, "income", amount=999999)
    result = analysis_service.get_net_position(db, 1)
    assert result["future_life_event_costs"] == 0 and result["net_position"] == 0


@pytest.mark.parametrize("period_report", [False, True])
def test_reports_exclude_income_from_progress_and_surplus_proposals(db, period_report):
    receipt = node(db, "income")
    reserve(db, receipt)
    expense = node(db)
    today = date.today()
    result = (report_service.generate_period_report(db, 1, today.replace(day=1), today)
              if period_report else report_service.generate_monthly_report(db, 1, today.year, today.month))
    assert [row["id"] for row in result["goal_progress"]] == [expense.id]
    allocations = [row for row in result["action_proposals"] if row["kind"] == "allocate_to_goal"]
    assert allocations and all(row["target_id"] == expense.id for row in allocations)


def test_stale_report_allocation_cannot_fund_income_event(db):
    receipt = node(db, "income")
    with pytest.raises(Refused):
        report_service._apply_allocate_to_goal(db, 1, "2026-10", {"target_id": receipt.id, "amount": 500})
    assert db.query(models.Transaction).count() == db.query(models.Account).count() == 0


def test_capsule_auto_creation_and_manual_link_refuse_income(db):
    receipt = node(db, "income")
    with pytest.raises(Refused):
        capsule_service.create_capsule_for_goal(db, 1, receipt)
    with pytest.raises(Refused):
        capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="積立", target_amount=100, monthly_contribution=0, life_event_id=receipt.id))
    cap = capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="手動", target_amount=100, monthly_contribution=0))
    with pytest.raises(Refused):
        capsule_service.update_capsule(db, 1, cap.id, schemas.CapsuleUpdate(life_event_id=receipt.id))
    assert cap.life_event_id is None


def test_milestone_defaults_and_preview_do_not_make_income_savings_plans(db):
    receipt = node(db, "income")
    assert milestone_service.build_default_milestone_rows(db, 1, receipt.id) == []
    for basis in ("annual_plan", "deterministic", "p50"):
        with pytest.raises(Refused):
            milestone_service.preview_milestones_from_simulation(db, 1, receipt.id, basis=basis)
    assert db.query(models.Milestone).count() == 0


def test_income_progress_condition_is_unknown_instead_of_underfunded(db):
    receipt, expense = node(db, "income"), node(db)
    life_event_conditions.create_condition(db, 1, expense.id, schemas.LifeEventConditionCreate(
        metric="goal_progress", comparator="gte", threshold_number=50, reference_id=receipt.id))
    result = life_event_conditions.evaluate(db, 1, expense.id)
    assert result["satisfied"] is None
    assert result["conditions"][0]["actual"] is None
    assert "積立進捗" in result["conditions"][0]["reason"]


def test_goal_monte_carlo_and_saved_savings_comparison_refuse_income(db):
    receipt = node(db, "income")
    with pytest.raises(Refused):
        monte_carlo_for_goal(db, 1, receipt.id, n_simulations=100, annual_return=None,
            inflation=None, monthly_savings=None, contribution_schedule=None, allocation_mode="direct")
    with pytest.raises(Refused):
        simulation_scenario_service.compare_scenarios(db, 1,
            schemas.SimulationScenarioCompareRequest(life_event_id=receipt.id, scenario_ids=[1, 2]))


def test_goal_capsule_and_boost_workflows_cannot_fund_income(db):
    receipt = node(db, "income")
    cash = account(db)
    with pytest.raises(Refused):
        capsule_workflow.create_goal_capsule(db, 1, receipt.id)
    with pytest.raises(Refused):
        monthly_action_workflow._apply_boost_allocation(db, models.MonthlyAction(
            client_id=1, payload={"life_event_id": receipt.id, "account_id": cash.id, "delta_percent": 10}))
    assert db.query(models.Capsule).count() == db.query(models.Transaction).count() == 0


def test_ai_savings_optimization_excludes_income_events(db, monkeypatch):
    from app.security import encrypt_key

    receipt = node(db, "income")
    receipt.name = "収入専用退職金"
    expense = node(db)
    expense.name = "支出専用学費"
    owner = db.get(models.Client, 1)
    owner.ai_config = {"gemini_api_key": encrypt_key("test-only")}
    db.commit()
    prompts = []

    async def capture_prompt(_key, prompt):
        prompts.append(prompt)
        return {"suggestions": []}

    monkeypatch.setattr(ai, "call_gemini", capture_prompt)
    asyncio.run(ai.optimize_allocations(db, owner))
    assert len(prompts) == 1
    assert json.dumps("支出専用学費") in prompts[0] and json.dumps("収入専用退職金") not in prompts[0]


def test_scenario_adds_resolved_income_and_subtracts_expense_in_their_years(db, monkeypatch):
    linked = account(db)
    expense = node(db, amount=100, offset=1)
    receipt = node(db, "income", amount=300, offset=10, account_id=linked.id)
    life_event_graph.create_link(db, 1, from_event_id=expense.id, to_event_id=receipt.id, kind="after", offset_months=12)
    year = date.today().year
    baseline = [{"year": year+i, "p10": 900, "p50": 1000, "p90": 1100} for i in range(4)]
    monkeypatch.setattr(life_event_graph, "simulate_net_worth_forward", lambda *a, **k: baseline)
    result = life_event_graph.compare_scenarios(db, 1, years=3, annual_return=0, inflation=0)
    scenario = result["scenarios"][0]
    assert scenario["events"][1]["resolved_date"] == date(year+2, 1, 1)
    assert scenario["events"][1]["direction"] == "income" and scenario["events"][1]["account_id"] == linked.id
    rows = scenario["projection"]
    for band, initial in (("p10", 900), ("p50", 1000), ("p90", 1100)):
        assert [row[band] for row in rows] == [initial, initial-100, initial+200, initial+200]
    assert [row["cumulative_target"] for row in rows] == [0, 100, 100, 100]
    assert [row["cumulative_income"] for row in rows] == [0, 0, 300, 300]
    assert [row["p50"] for row in baseline] == [1000]*4


def test_scenario_receipts_are_counted_only_on_the_selected_branch(db, monkeypatch):
    root = node(db, amount=0)
    a, b = node(db, "income", amount=100), node(db, "income", amount=300)
    archived = node(db, "income", amount=999, archived_at=datetime.utcnow())
    for child in (a, b, archived):
        if child is not archived:
            life_event_graph.create_link(db, 1, from_event_id=root.id, to_event_id=child.id, kind="alternative")
    year = date.today().year
    baseline = [{"year": year+i, "p10": 1000, "p50": 1000, "p90": 1000} for i in range(4)]
    monkeypatch.setattr(life_event_graph, "simulate_net_worth_forward", lambda *a, **k: baseline)
    scenarios = life_event_graph.enumerate_scenarios(db, 1)
    rows = [life_event_graph.project_scenario(db, 1, item, years=3, annual_return=0, inflation=0) for item in scenarios]
    assert [item[-1]["p50"] for item in rows] == [1100, 1300]
    assert [item[-1]["cumulative_income"] for item in rows] == [100, 300]


def test_roadmap_net_worth_adds_income_while_liability_demand_stays_expense_only(db):
    db.add(models.SimulationConfig(client_id=1, monthly_savings_minor=0, volatility=0, annual_return=0, inflation_rate=0))
    db.commit()
    node(db, amount=100, offset=1)
    receipt = node(db, "income", amount=300, offset=2)
    node(db, "income", amount=9999, offset=1, archived_at=datetime.utcnow())
    result = strategy_service.get_roadmap_projection(db, 1, years=3, annual_return=0, inflation=0)
    assert [row["p50"] for row in result["projection"]] == [0, 0, 300, 300]
    assert [row["cumulative_target"] for row in result["liability_demand"]] == [0, 100, 100, 100]
    assert [row["event_count"] for row in result["liability_demand"]] == [0, 1, 1, 1]
    assert next(row for row in result["events"] if row["id"] == receipt.id)["direction"] == "income"


def test_forward_net_worth_counts_income_and_scenario_baseline_can_opt_out(db):
    node(db, "income", amount=300, offset=1)
    node(db, amount=100, offset=1)
    db.add(models.SimulationConfig(client_id=1, monthly_savings_minor=0, volatility=0))
    db.commit()
    rows = strategy_service.simulate_net_worth_forward(db, 1, years=2, annual_return=0, inflation=0)
    assert [row["p50"] for row in rows] == [0, 300, 300]
    baseline = strategy_service.simulate_net_worth_forward(db, 1, years=2, annual_return=0, inflation=0, include_event_income=False)
    assert [row["p50"] for row in baseline] == [0, 0, 0]


@pytest.mark.parametrize("stored", [False, True])
def test_scenario_query_defaults_overrides_and_reported_parameters(db, api, stored):
    db.add(models.SimulationConfig(client_id=2, horizon_years=55, annual_return=9, inflation_rate=4))
    db.commit()
    if stored:
        db.add(models.SimulationConfig(client_id=1, horizon_years=7, annual_return=3.5, inflation_rate=1.2))
        db.commit()
    defaults = {"years": 7, "annual_return": 3.5, "inflation": 1.2} if stored else {"years": 30, "annual_return": 5.0, "inflation": 2.0}
    for query, expected in (("", defaults), ("?years=2&annual_return=0&inflation=0", {"years": 2, "annual_return": 0, "inflation": 0}),
                            ("?annual_return=0", {**defaults, "annual_return": 0})):
        response = request(api, "GET", f"/life-events/scenarios{query}")
        assert response.status_code == 200
        assert response.json()["parameters"] == expected
        assert len(response.json()["scenarios"][0]["projection"]) == expected["years"]+1
    assert db.query(models.SimulationConfig).filter_by(client_id=1).count() == int(stored)


def test_simulation_config_horizon_round_trips_get_post_put(db, api):
    assert request(api, "GET", "/simulation/config").json()["horizon_years"] == 30
    assert db.query(models.SimulationConfig).count() == 0
    assert request(api, "POST", "/simulation/config", json={"horizon_years": 1}).json()["horizon_years"] == 1
    assert request(api, "PUT", "/simulation/config", json={"horizon_years": 60}).json()["horizon_years"] == 60
    assert request(api, "GET", "/simulation/config").json()["horizon_years"] == 60
    assert request(api, "GET", "/life-events/scenarios").json()["parameters"]["years"] == 60


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("horizon", [0, 61])
def test_simulation_config_rejects_invalid_horizon(db, api, method, horizon):
    assert request(api, method, "/simulation/config", json={"horizon_years": horizon}).status_code == 422
    assert db.query(models.SimulationConfig).count() == 0


def test_v21_backup_round_trips_income_account_and_horizon_without_auto_capsules(db):
    linked = account(db)
    receipt = node(db, "income", account_id=linked.id)
    db.add(models.SimulationConfig(client_id=1, horizon_years=17))
    db.commit()
    document = export_client(db, db.get(models.Client, 1))
    assert document["version"] == EXPORT_VERSION == 21
    assert document["data"]["life_events"][0]["direction"] == "income"
    assert document["data"]["life_events"][0]["account_id"] == linked.id
    assert document["data"]["simulation_configs"][0]["horizon_years"] == 17
    import_client(db, db.get(models.Client, 2), data=document["data"], version=EXPORT_VERSION, manifest=document["manifest"])
    restored = db.query(models.LifeEvent).filter_by(client_id=2).one()
    assert restored.id != receipt.id and restored.account_id != linked.id
    assert restored.direction == "income" and db.get(models.Account, restored.account_id).client_id == 2
    assert db.query(models.SimulationConfig).filter_by(client_id=2).one().horizon_years == 17
    assert db.query(models.Capsule).filter_by(client_id=2).count() == 0


def test_v19_backup_without_new_fields_imports_compatibility_defaults(db):
    linked = account(db)
    node(db, "income", account_id=linked.id)
    db.add(models.SimulationConfig(client_id=1, horizon_years=17))
    db.commit()
    data = export_client(db, db.get(models.Client, 1))["data"]
    del data["life_events"][0]["direction"], data["life_events"][0]["account_id"]
    del data["simulation_configs"][0]["horizon_years"]
    import_client(db, db.get(models.Client, 2), data=data, version=19, manifest=None)
    restored = db.query(models.LifeEvent).filter_by(client_id=2).one()
    assert restored.direction == "expense" and restored.account_id is None
    assert db.query(models.SimulationConfig).filter_by(client_id=2).one().horizon_years == 30
    assert db.query(models.Capsule).filter_by(client_id=2).count() == 1


@pytest.mark.parametrize("collection, patch, code", [
    ("life_events", {"account_id": 9999}, "missing_reference"),
    ("life_events", {"direction": "invalid"}, "invalid_direction"),
    ("simulation_configs", {"horizon_years": 0}, "invalid_horizon_years"),
    ("simulation_configs", {"horizon_years": 61}, "invalid_horizon_years"),
])
def test_backup_validates_new_fields_before_import(db, collection, patch, code):
    node(db)
    db.add(models.SimulationConfig(client_id=1))
    db.commit()
    data = export_client(db, db.get(models.Client, 1))["data"]
    data[collection][0].update(patch)
    assert any(row["code"] == code for row in validate_import_payload(data, 20)["issues"])


@pytest.mark.parametrize("model, fields", [
    (models.LifeEvent, {"direction": "invalid"}),
    (models.SimulationConfig, {"horizon_years": 0}),
    (models.SimulationConfig, {"horizon_years": 61}),
])
def test_new_database_checks_reject_invalid_stored_values(db, model, fields):
    db.add(model(client_id=1, **fields))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
