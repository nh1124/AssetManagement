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
from app.services import capsule_service, registry_service
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


def test_every_range_funds_far_events_through_capsules_too(db, story):
    result = workflow.preview(db, 1, options(near_years=None))
    rows = {row["name"]: row for row in result["events"]}
    assert all(row["near"] for row in result["events"])
    # The home has no capsule, so it now asks for one like any near event.
    assert rows["住宅"]["status"] == "no_capsule"
    # In cash, without the after-tax return: 10,000,000 over 240 months.
    assert rows["住宅"]["monthly_required"] == 41667
    assert result["options"]["near_years"] is None



def existing_savings(db, story):
    bank = create_account(db, 1, {"name": "給与口座", "account_type": "asset"})
    db.commit()
    definition = registry_service.create_entry(db, 1, {
        "name": "投資積立", "amount": 20000, "currency": "JPY", "frequency": "Monthly",
        "line_type": "allocation", "source_account_id": bank.id, "destination_account_id": story["savings"].id,
    })
    yearly = registry_service.create_entry(db, 1, {
        "name": "年払いの積立", "amount": 12000, "currency": "JPY", "frequency": "Yearly", "month_of_year": 11,
        "line_type": "allocation", "source_account_id": bank.id, "destination_account_id": story["other"].id,
    })
    loose = capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="予備費", target_amount=100000, monthly_contribution=5000))
    return definition, yearly, loose


def test_existing_savings_count_toward_the_total_so_nothing_is_planned_twice(db, story):
    definition, yearly, loose = existing_savings(db, story)
    result = workflow.preview(db, 1, options(savings_account_id=story["savings"].id))
    rows = {row["name"]: row for row in result["existing"]}
    assert (rows["投資積立"]["kind"], rows["投資積立"]["amount"], rows["投資積立"]["updatable"]) == ("definition", 20000, True)
    # November is the yearly entry's month; it counts, but only a monthly amount can be rewritten.
    assert (rows["年払いの積立"]["amount"], rows["年払いの積立"]["updatable"]) == (12000, False)
    assert (rows["予備費"]["kind"], rows["予備費"]["amount"]) == ("capsule", 5000)
    # The goal's own capsule is written by the reflection, never counted as existing.
    assert "車の取り置き" not in rows
    savings = result["savings"]
    assert (savings["existing_amount"], savings["capsule_amount"], savings["account_amount"]) == (37000, 10000, 3000)
    # Leaving a transfer out gives its amount back to the goal row.
    fewer = workflow.preview(db, 1, options(savings_account_id=story["savings"].id, uncounted=[f"definition:{definition.id}"]))
    assert fewer["savings"]["account_amount"] == 23000
    assert next(row for row in fewer["existing"] if row["name"] == "投資積立")["counted"] is False


def test_hand_entered_allocations_count_per_month(db, story):
    chosen = options(savings_account_id=story["savings"].id, months=2)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    from app.services.budget_plan_store import create_plan_lines
    create_plan_lines(db, 1, [{"target_period": "2026-12", "line_type": "allocation", "target_type": "account",
                               "account_id": story["other"].id, "name": "手入力の積立", "amount": 15000}])
    result = workflow.preview(db, 1, chosen)
    manual = next(row for row in result["existing"] if row["kind"] == "manual")
    assert (manual["name"], manual["amount"]) == ("手入力の積立", 0)  # nothing in November
    by_period = {row["period"]: row["new_amount"] for row in result["changes"] if row["kind"] == "savings"}
    assert by_period == {"2026-11": 40000, "2026-12": 25000}


def test_a_monthly_definition_can_carry_the_goal_savings(db, story):
    definition, _, _ = existing_savings(db, story)
    first = options(savings_account_id=story["other"].id)
    workflow.apply(db, 1, first, workflow.preview(db, 1, first)["fingerprint"])
    chosen = options(savings_definition_id=definition.id)
    preview = workflow.preview(db, 1, chosen)
    assert next(row for row in preview["existing"] if row["id"] == definition.id and row["kind"] == "definition")["destination"] is True
    # 50,000 - 10,000 car - 12,000 yearly - 5,000 reserve, now carried by the definition.
    change = next(row for row in preview["changes"] if row["kind"] == "definition")
    assert (change["current_amount"], change["new_amount"]) == (20000, 23000)
    # The earlier goal row would double it, so it is retired.
    assert [row["kind"] for row in preview["changes"]] == ["capsule", "retire", "definition"]
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    db.refresh(definition)
    assert definition.amount == 23000
    assert db.query(models.MonthlyPlanLine).filter_by(source_kind="goal", is_active=True).count() == 0


def test_destination_must_be_one_updatable_definition_or_one_account(db, story):
    definition, yearly, _ = existing_savings(db, story)
    with pytest.raises(NotFound):
        workflow.preview(db, 1, options(savings_definition_id=yearly.id))
    with pytest.raises(Refused):
        workflow.preview(db, 1, options(savings_definition_id=definition.id, savings_account_id=story["savings"].id))



def codes(result):
    return [row["code"] for row in result["reminders"]]


def test_status_breaks_savings_down_and_asks_for_a_first_reflection(db, story):
    result = workflow.status(db, 1, START)
    rows = {row["name"]: row for row in result["events"]}
    assert result["goal"]["monthly_savings"] == 50000
    assert (rows["車"]["kind"], rows["車"]["allocation"], rows["車"]["source"]) == ("near", 10000, "rule")
    assert rows["別荘"]["kind"] == "simulation_only" and rows["別荘"]["allocation"] == 0
    assert rows["退職金"]["kind"] == "income"
    assert codes(result) == ["never"]


def test_status_reminds_when_the_reflection_runs_out_or_the_goal_moves(db, story):
    chosen = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    now = workflow.status(db, 1, START)
    # The budget now carries the whole 50,000: car capsule plus the goal row.
    assert now["budget"]["total"] == 50000 and now["budget"]["difference"] == 0
    assert codes(now) == ["coverage_ending"]
    assert {row["name"]: row["source"] for row in now["events"]}["車"] == "reflection"
    assert codes(workflow.status(db, 1, "2026-12"))[0] == "coverage_ended"
    story["car"].target_amount_minor = 300000
    db.add(models.LifeEvent(client_id=1, scenario_id=story["car"].scenario_id, name="新車", target_date=date(2030, 1, 1),
                            target_amount_minor=100))
    db.commit()
    from app.services import life_scenario_service
    life_scenario_service.update(db, 1, story["car"].scenario_id, {"monthly_savings": 60000})
    later = codes(workflow.status(db, 1, START))
    assert "savings_changed" in later and "events_changed" in later and "budget_drift" in later


def test_a_far_event_entering_the_range_suggests_a_handover(db, story):
    chosen = options(savings_account_id=story["savings"].id, months=3)
    preview = workflow.preview(db, 1, chosen)
    home = next(row for row in preview["events"] if row["name"] == "住宅")
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    # Five years before the home's target month it becomes near.
    result = workflow.status(db, 1, "2042-01")
    near = next(row for row in result["reminders"] if row["code"] == "event_near")
    assert near["event_id"] == story["home"].id
    # Three reflected months of its far share were planned into the savings.
    assert near["handover_amount"] == pytest.approx(home["allocation"] * 3)
