"""Reflecting the goal into the budget: previewed exactly, applied only as confirmed."""
import asyncio
from datetime import date

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, NotFound, Refused, detail_for, status_for
from app.routers.goal_budget import router
from app.services import capsule_service
from app.services.ledger_service import create_account
from app.workflows import goal_budget_workflow as workflow
from scenario_fixtures import goal_scenario_id

START = "2026-11"


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
        session.add(models.SimulationConfig(client_id=1, annual_return=5, inflation_rate=2, horizon_years=30,
                                            monthly_savings_minor=50000, tax_rate=20, volatility=15))
        session.commit()
        yield session
    engine.dispose()


def add_event(db, name, target, amount, **values):
    row = models.LifeEvent(client_id=1, scenario_id=goal_scenario_id(db, 1), name=name,
                           target_date=target, target_amount_minor=amount, **values)
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def story(db):
    car = add_event(db, "車", date(2028, 11, 30), 240000)
    capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="車の取り置き", life_event_id=car.id,
                                                                target_amount=240000, monthly_contribution=0))
    study = add_event(db, "留学", date(2027, 11, 1), 120000)
    db.add(models.LifeEventCondition(client_id=1, life_event_id=study.id, metric="date_reached",
                                     comparator="gte", threshold_date=date(2099, 1, 1)))
    trip = add_event(db, "旅行", date(2027, 5, 1), 60000)
    idea = add_event(db, "別荘", date(2027, 5, 1), 900000, budget_reflection="simulation_only")
    home = add_event(db, "住宅", date(2046, 11, 1), 10000000)
    bonus = add_event(db, "退職金", date(2050, 1, 1), 5000000, direction="income")
    db.commit()
    savings = create_account(db, 1, {"name": "運用口座", "account_type": "asset"})
    other = create_account(db, 1, {"name": "別の口座", "account_type": "asset"})
    db.commit()
    return {"car": car, "study": study, "trip": trip, "idea": idea, "home": home, "bonus": bonus,
            "savings": savings, "other": other}


def options(**values):
    return {"savings_source": "scenario", "near_years": 5, "start_period": START, "months": 1,
            "savings_account_id": None, "create_capsules": [], **values}


def snapshot(db):
    return (db.query(models.MonthlyPlanLine).count(), db.query(models.Capsule).count(),
            db.query(models.BudgetPlan).count())


def test_preview_classifies_every_event_and_writes_nothing(db, story):
    before = snapshot(db)
    result = workflow.preview(db, 1, options(savings_account_id=story["savings"].id))
    status = {row["name"]: row["status"] for row in result["events"]}
    assert status == {"車": "reflected", "留学": "condition_unmet", "旅行": "no_capsule",
                      "別荘": "simulation_only", "住宅": "reflected", "退職金": "income"}
    rows = {row["name"]: row for row in result["events"]}
    assert rows["留学"]["reflection"] == "conditional" and rows["留学"]["conditions_total"] == 1
    assert rows["留学"]["conditions_met"] == 0
    # 24 cash contributions fund the car; the far home assumes the after-tax return.
    assert rows["車"]["monthly_required"] == 10000 and rows["車"]["near"] is True
    assert rows["住宅"]["near"] is False and 0 < rows["住宅"]["monthly_required"] < 10000000 / 240
    assert result["savings"]["capsule_amount"] == 10000
    assert result["savings"]["account_amount"] == 40000
    assert [(row["kind"], row["new_amount"], row["line_id"]) for row in result["changes"]] == [
        ("capsule", 10000, None), ("savings", 40000, None)]
    assert snapshot(db) == before


def test_required_savings_counts_only_reflected_events(db, story):
    result = workflow.preview(db, 1, options(savings_source="required"))
    rows = {row["name"]: row for row in result["events"]}
    # The trip still needs funding even without a capsule; excluded events do not.
    assert result["savings"]["required_amount"] == rows["車"]["monthly_required"] + rows["旅行"]["monthly_required"] + rows["住宅"]["monthly_required"]
    assert result["savings"]["chosen_amount"] == result["savings"]["required_amount"]
    assert result["savings"]["account_required"] is True
    assert [row["kind"] for row in result["changes"]] == ["capsule"]


def test_apply_writes_the_confirmed_months_and_creates_requested_capsules(db, story):
    chosen = options(savings_account_id=story["savings"].id, months=2, create_capsules=[story["trip"].id])
    preview = workflow.preview(db, 1, chosen)
    trip = next(row for row in preview["events"] if row["name"] == "旅行")
    assert trip["status"] == "reflected" and trip["create_capsule"] is True
    assert trip["monthly_required"] == 10000  # 60,000 over the six months to May.
    result = workflow.apply(db, 1, chosen, preview["fingerprint"])
    assert result["applied"] == 6 and [row["name"] for row in result["created_capsules"]] == ["旅行"]
    lines = db.query(models.MonthlyPlanLine).order_by(models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id).all()
    assert [(line.target_period, line.target_type, line.source_kind, line.amount) for line in lines] == [
        ("2026-11", "capsule", "capsule", 10000), ("2026-11", "capsule", "capsule", 10000), ("2026-11", "account", "goal", 30000),
        ("2026-12", "capsule", "capsule", 10000), ("2026-12", "capsule", "capsule", 10000), ("2026-12", "account", "goal", 30000),
    ]
    car_capsule = db.query(models.Capsule).filter_by(life_event_id=story["car"].id).one()
    assert car_capsule.monthly_contribution == 10000
    # Applying the same choices again finds the rows instead of adding to them.
    again = workflow.preview(db, 1, chosen | {"create_capsules": []})
    assert all(row["line_id"] is not None and not row["changed"] for row in again["changes"])


def test_stale_fingerprint_is_refused_and_writes_nothing(db, story):
    chosen = options(savings_account_id=story["savings"].id)
    preview = workflow.preview(db, 1, chosen)
    story["car"].target_amount_minor = 480000
    db.commit()
    before = snapshot(db)
    with pytest.raises(Conflict):
        workflow.apply(db, 1, chosen, preview["fingerprint"])
    assert snapshot(db) == before


def test_another_savings_account_replaces_the_earlier_reflection(db, story):
    first = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, first, workflow.preview(db, 1, first)["fingerprint"])
    second = options(savings_account_id=story["other"].id)
    preview = workflow.preview(db, 1, second)
    assert preview["savings"]["suggested_account_id"] == story["savings"].id
    assert [row["kind"] for row in preview["changes"]] == ["capsule", "savings", "retire"]
    workflow.apply(db, 1, second, preview["fingerprint"])
    goal_lines = db.query(models.MonthlyPlanLine).filter_by(source_kind="goal", is_active=True).all()
    assert [(line.account_id, line.amount) for line in goal_lines] == [(story["other"].id, 40000)]


def test_edited_rows_are_shown_with_their_current_amount_and_reset(db, story):
    chosen = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    line = db.query(models.MonthlyPlanLine).filter_by(source_kind="goal").one()
    line.amount_minor, line.manual_override = 12345, True
    db.commit()
    preview = workflow.preview(db, 1, chosen)
    savings = next(row for row in preview["changes"] if row["kind"] == "savings")
    assert (savings["current_amount"], savings["new_amount"], savings["changed"]) == (12345, 40000, True)
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    db.refresh(line)
    assert (line.amount, line.manual_override) == (40000, False)


@pytest.mark.parametrize("pick", ["liability", "foreign", "inactive"])
def test_savings_account_must_be_an_active_asset_of_the_client(db, story, pick):
    if pick == "liability":
        account = create_account(db, 1, {"name": "カード", "account_type": "liability"})
    elif pick == "foreign":
        account = create_account(db, 2, {"name": "他人の口座", "account_type": "asset"})
    else:
        account = story["other"]
        account.is_active = False
    db.commit()
    with pytest.raises(NotFound):
        workflow.preview(db, 1, options(savings_account_id=account.id))


def test_client_without_goal_is_told_to_choose_one(db):
    with pytest.raises(Refused):
        workflow.preview(db, 2, options())


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
            pytest.fail("HTTP goal budget request timed out")
    return asyncio.run(run())


def test_http_preview_apply_and_validation(db, api, story):
    body = options(savings_account_id=story["savings"].id)
    preview = request(api, "POST", "/goal-budget/preview", json=body)
    assert preview.status_code == 200
    applied = request(api, "POST", "/goal-budget/apply", json=body | {"fingerprint": preview.json()["fingerprint"]})
    assert applied.status_code == 200 and applied.json()["applied"] == 2
    stale = request(api, "POST", "/goal-budget/apply", json=body | {"months": 2, "fingerprint": preview.json()["fingerprint"]})
    assert stale.status_code == 409
    for invalid in ({"start_period": "2026-13"}, {"near_years": 0}, {"months": 13}, {"savings_source": "guess"}):
        assert request(api, "POST", "/goal-budget/preview", json=body | invalid).status_code == 422
