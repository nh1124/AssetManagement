"""Duplicating a story must never duplicate the user's real savings plan."""
import asyncio
from datetime import date, datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.journal import Leg
from app.routers import ai_operations, analysis, budget_plans, capsules, data_transfer, life_events, reports, roadmap
from app.services import capsule_service, goal_service, life_event_conditions, life_scenario_service, strategy_service
from app.services.budget_context import BudgetContext
from app.services.cache_service import invalidate_client
from app.services.ledger_service import create_transaction
from app.services.milestone_service import preview_milestones_from_simulation


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"}) for i in (1, 2)])
        session.commit()
        invalidate_client()
        yield session
        invalidate_client()
    engine.dispose()


def event(db, scenario_id, name, amount, *, direction="expense", priority=2, archived=False, client_id=1):
    row = models.LifeEvent(
        client_id=client_id, scenario_id=scenario_id, name=name, direction=direction,
        target_amount_minor=amount, target_date=date(date.today().year + 3, 6, 1), priority=priority,
        archived_at=datetime(2026, 1, 1) if archived else None,
    )
    db.add(row)
    db.flush()
    return row


def seed(db):
    goal_id = models.LifeScenario(client_id=1, name="Goal", is_goal=True)
    foreign = models.LifeScenario(client_id=2, name="Other client's goal", is_goal=True)
    db.add_all([goal_id, foreign])
    db.flush()
    first = event(db, goal_id.id, "Home", 8_000_000, priority=1)
    second = event(db, goal_id.id, "Education", 12_000_000, priority=3)
    event(db, goal_id.id, "Receipt", 300_000, direction="income")
    event(db, goal_id.id, "Archived", 99_000_000, archived=True)
    event(db, foreign.id, "Foreign", 999_000_000, client_id=2)
    db.add_all([
        models.SimulationConfig(client_id=1, monthly_savings_minor=30_000),
        models.Milestone(client_id=1, life_event_id=first.id, date=first.target_date, target_amount_minor=8_000_000),
        models.Milestone(client_id=1, date=first.target_date, target_amount_minor=10, note="Standalone"),
        models.LifeEventCondition(client_id=1, life_event_id=first.id, metric="goal_progress",
                                  reference_id=second.id, comparator="gte", threshold_number=50),
    ])
    cash = models.Account(client_id=1, name="cash", account_type="asset")
    income = models.Account(client_id=1, name="Salary", account_type="income")
    db.add_all([cash, income])
    db.flush()
    capsule = capsule_service.create_capsule_for_goal(db, 1, first)
    create_transaction(db, client_id=1, date=date(2020, 1, 1), description="Existing earmark",
                       amount_minor=100_000, currency="JPY",
                       legs=[Leg(cash.id, debit=100_000, capsule_id=capsule.id), Leg(income.id, credit=100_000)])
    db.commit()
    return goal_id, first, capsule


def application(db):
    app = FastAPI()
    for module in (life_events, roadmap, reports, budget_plans, analysis, ai_operations, capsules, data_transfer):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)
    # Mixed app/backend.app imports can give module-style routers a distinct dependency identity.
    for module in (roadmap, capsules):
        app.dependency_overrides[module.dependencies.get_current_client] = lambda: db.get(models.Client, 1)
        app.dependency_overrides[module.database.get_db] = lambda: db
    return app


def snapshot(app, *, fresh=True):
    today = date.today()
    period = today.strftime("%Y-%m")
    urls = {
        "events": "/life-events/",
        "progress": "/life-events/with-progress",
        "archived_progress": "/life-events/with-progress?include_archived=true",
        "dashboard": "/life-events/dashboard",
        "roadmap": "/roadmap/projection?years=5",
        "milestones": "/roadmap/milestones",
        "monthly": f"/reports/monthly?year={today.year}&month={today.month}",
        "period": f"/reports/period?start_date={today.replace(day=1)}&end_date={today}",
        "funding": f"/budget-plans/summary?period={period}",
        "ai": "/ai/context/resource/goals",
        "analysis": "/analysis/summary",
        "conditions": "/life-events/conditions",
        "capsules": "/capsules/",
        "health": "/data/health",
    }
    if fresh:
        # Fresh reads prevent a warm endpoint cache from hiding an unscoped query.
        invalidate_client(1)

    async def run():
        result = {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for name, url in urls.items():
                response = await client.get(url)
                assert response.status_code == 200, (url, response.text)
                result[name] = response.json()
        result["ai"].pop("generated_at")
        session = app.dependency_overrides[get_db]()
        result["probability"] = strategy_service.calculate_overall_goal_probability(session, client_id=1)
        return result

    return asyncio.run(run())


def test_duplicate_and_draft_only_events_leave_every_goal_endpoint_unchanged_then_goal_switch_updates_them(db):
    goal, original, capsule = seed(db)
    app = application(db)
    before = snapshot(app)
    assert before["probability"]["total_goals"] == 2
    assert before["probability"]["total_target"] == 20_000_000
    assert before["funding"]["total_goal_gap"] > 0
    assert before["progress"][0]["current_funded"] == 100_000
    assert before["capsules"][0]["current_balance"] == 100_000
    assert len(before["roadmap"]["milestones"]) == 2
    assert before["ai"]["data"]["count"] == 3

    duplicate = life_scenario_service.duplicate(db, 1, goal.id, "Copy")
    assert db.query(models.LifeEvent).filter_by(client_id=1).count() == 8
    assert snapshot(app) == before

    draft_only = event(db, duplicate.id, "Draft expense", 30_000_000, priority=1)
    event(db, duplicate.id, "Draft receipt", 7_000_000, direction="income")
    db.add(models.Milestone(client_id=1, life_event_id=draft_only.id, date=draft_only.target_date,
                            target_amount_minor=30_000_000))
    db.commit()
    assert snapshot(app) == before

    # Populate caches before switching: adopting a different story must invalidate them too.
    life_scenario_service.make_goal(db, 1, duplicate.id)
    after = snapshot(app, fresh=False)
    active = goal_service.goal_events_query(db, 1).all()
    ids = {row.id for row in active}
    expense_ids = {row.id for row in active if row.direction == "expense"}
    assert {row["id"] for row in after["progress"]} == ids
    assert {row["id"] for row in after["probability"]["goals"]} == expense_ids
    assert after["probability"]["total_target"] == 50_000_000
    assert after["probability"]["total_goals"] == 3
    assert after["probability"]["overall_probability"] != before["probability"]["overall_probability"]
    for key in ("monthly", "period"):
        assert {row["id"] for row in after[key]["goal_progress"]} == expense_ids
    for key in ("roadmap", "dashboard"):
        assert {row["id"] for row in after[key]["events"]} == ids
    assert after["roadmap"]["liability_demand"][-1]["cumulative_target"] == 50_000_000
    assert after["roadmap"]["liability_demand"][-1]["cumulative_income"] == 7_300_000
    assert after["roadmap"]["projection"] != before["roadmap"]["projection"]
    assert after["funding"]["goals_count"] == 3
    assert after["funding"]["total_goal_gap"] != before["funding"]["total_goal_gap"]
    assert {row["id"] for row in after["ai"]["data"]["goals"]} == ids
    assert after["analysis"]["total_goal_count"] == 3
    assert after["analysis"]["total_goal_amount"] == 50_000_000
    assert {row["life_event_id"] for row in after["milestones"] if row["life_event_id"]} <= ids
    assert {row["life_event_id"] for row in after["roadmap"]["milestones"] if row["life_event_id"]} <= ids
    assert original.id not in {int(key) for key in after["conditions"]}
    assert after["capsules"][0]["current_balance"] == 100_000
    assert after["capsules"][0]["life_event_id"] in expense_ids
    assert db.get(models.Capsule, capsule.id).id == capsule.id


def test_missing_goal_never_falls_back_to_draft_or_another_clients_goal(db):
    goal, _, _ = seed(db)
    goal.is_goal = False
    db.commit()
    assert goal_service.goal_events_query(db, 1, include_archived=True).all() == []
    result = snapshot(application(db))
    for key in ("events", "progress", "archived_progress"):
        assert result[key] == []
    assert result["probability"]["total_goals"] == 0
    assert result["monthly"]["goal_progress"] == result["period"]["goal_progress"] == []
    assert result["ai"]["data"] == {"count": 0, "goals": []}
    assert result["analysis"]["total_goal_count"] == result["funding"]["goals_count"] == 0
    assert result["roadmap"]["events"] == []
    assert all(row["cumulative_target"] == row["cumulative_income"] == 0 for row in result["roadmap"]["liability_demand"])
    assert all(row["life_event_id"] is None for row in result["milestones"])
    assert result["conditions"] == {}


def test_scope_preserves_archive_option_scenario_editor_and_record_name_resolution(db):
    goal, original, _ = seed(db)
    copy = life_scenario_service.duplicate(db, 1, goal.id, "Draft")
    assert len(goal_service.goal_events_query(db, 1).all()) == 3
    assert len(goal_service.goal_events_query(db, 1, include_archived=True).all()) == 4
    assert goal_service.goal_events_query(db, 999).all() == []
    draft_events = goal_service.list_goals(db, 1, scenario_id=copy.id)
    assert len(draft_events) == 3 and all(row.scenario_id == copy.id for row in draft_events)
    assert goal_service.get_life_event(db, 1, draft_events[0].id).scenario_id == copy.id
    assert goal_service.get_life_event(db, 2, original.id) is None
    # Budget labels resolve stored references even after those events stop being the plan.
    assert draft_events[0].id in BudgetContext(db, 1).target_name_maps["life_event"]
    context = strategy_service.get_goal_simulation_context(db, 1, original)
    # Both events are near and together need more than the 30,000 saved, so they
    # share it in proportion to their shortfall (Home has 100,000 earmarked).
    assert context["allocation_source"] == "rule"
    assert context["allocated_monthly_savings"] == pytest.approx(30_000 * 7_900_000 / 19_900_000)
    # Savings are shared within one story, so a draft event competes only with its
    # own scenario's events. The draft's copy holds no earmark (capsules stay with
    # the goal), so its shortfall and share are larger; the goal's stay as they were.
    draft_context = strategy_service.get_goal_simulation_context(db, 1, draft_events[0])
    assert draft_context["allocated_monthly_savings"] == pytest.approx(30_000 * 8_000_000 / 20_000_000)


def test_current_progress_conditions_treat_a_draft_reference_as_unknown_until_adopted(db):
    goal, original, _ = seed(db)
    draft = life_scenario_service.duplicate(db, 1, goal.id, "Draft")
    copied = goal_service.list_goals(db, 1, scenario_id=draft.id)
    expense = next(row for row in copied if row.direction == "expense")
    condition = life_event_conditions.create_condition(db, 1, original.id, schemas.LifeEventConditionCreate(
        metric="goal_progress", reference_id=expense.id, comparator="gte", threshold_number=0,
    ))
    result = life_event_conditions.evaluate(db, 1, original.id)
    detail = next(row for row in result["conditions"] if row["id"] == condition.id)
    assert detail["actual"] is detail["satisfied"] is detail["reference_name"] is None
    assert detail["reason"]
    life_scenario_service.make_goal(db, 1, draft.id)
    # Explicit record inspection remains possible; the referenced current fact now exists.
    result = life_event_conditions.evaluate(db, 1, original.id)
    detail = next(row for row in result["conditions"] if row["id"] == condition.id)
    assert detail["actual"] is not None and detail["satisfied"] is True


def test_milestone_generation_ignores_copied_goals(db):
    goal, original, _ = seed(db)
    before = preview_milestones_from_simulation(db, 1, original.id, basis="deterministic")
    duplicate = life_scenario_service.duplicate(db, 1, goal.id, "Draft")
    event(db, duplicate.id, "Draft only", 100_000_000)
    db.commit()
    after = preview_milestones_from_simulation(db, 1, original.id, basis="deterministic")
    # Generation timestamps describe the read, not the financial plan.
    for preview in (before, after):
        for row in preview["items"]:
            row["source_snapshot"].pop("generated_at", None)
    assert after == before
