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
from product_saves import confirmed
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
    # A capsule funded from an account shows in the budget, so it counts.
    loose = capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="予備費", target_amount=100000, monthly_contribution=5000,
                                                                         account_id=story["other"].id))
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



# --- Review fixes (R1): each test names the defect it guards against. ---

def plan_lines(db, **filters):
    return db.query(models.MonthlyPlanLine).filter_by(is_active=True, **filters).order_by(
        models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id).all()


def test_a_definition_saved_for_the_month_counts_once(db, story):
    from app.services.budget_plan_store import create_plan_lines
    definition, _, _ = existing_savings(db, story)
    # The user saved the definition's month at its own amount; the budget merges the two.
    create_plan_lines(db, 1, [{"target_period": START, "line_type": "allocation", "target_type": "account",
                               "account_id": story["savings"].id, "amount": 20000}])
    rows = [row for row in workflow.preview(db, 1, options())["existing"] if row["amount"]]
    assert sorted((row["kind"], row["amount"]) for row in rows) == [("capsule", 5000), ("definition", 12000), ("definition", 20000)]


def test_a_capsule_absent_from_the_budget_does_not_count(db, story):
    capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="口座なし", target_amount=1000, monthly_contribution=5000))
    assert workflow.preview(db, 1, options())["existing"] == []


def test_a_near_capsule_stops_at_its_target_month(db, story):
    story["trip"].target_date = date(2026, 12, 15)
    db.commit()
    chosen = options(savings_account_id=story["savings"].id, months=3, create_capsules=[story["trip"].id])
    preview = workflow.preview(db, 1, chosen)
    trip = [(row["period"], row["new_amount"]) for row in preview["changes"] if row["kind"] == "capsule" and row["name"] == "旅行"]
    # Funded in November only (one month before December); later months write nothing.
    # November's near events need 70,000 of the 50,000, so the trip and the car share it.
    assert trip[0] == ("2026-11", 42857) and all(amount == 0 for _, amount in trip[1:])
    assert preview["savings"]["shortfall"] == 20000
    savings = {row["period"]: row["new_amount"] for row in preview["changes"] if row["kind"] == "savings"}
    assert savings == {"2026-11": 0, "2026-12": 40000, "2027-01": 40000}


def test_a_legacy_life_event_row_is_updated_not_duplicated(db, story):
    from app.services.budget_plan_store import create_plan_lines, get_or_create_default_plan
    plan = get_or_create_default_plan(db, 1)
    legacy = models.MonthlyPlanLine(client_id=1, plan_id=plan.id, target_period=START, line_type="allocation",
                                    target_type="life_event", target_id=story["car"].id, amount_minor=777)
    db.add(legacy)
    db.commit()
    chosen = options()
    preview = workflow.preview(db, 1, chosen)
    car = [row for row in preview["changes"] if row["kind"] == "capsule"]
    assert [(row["line_id"], row["current_amount"], row["new_amount"]) for row in car] == [(legacy.id, 777, 10000)]
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    assert [line.amount for line in plan_lines(db, target_period=START, line_type="allocation")] == [10000]


def test_an_accountless_row_is_split_when_the_capsule_has_several_accounts(db, story):
    from app.services.budget_plan_store import get_or_create_default_plan
    car_capsule = db.query(models.Capsule).filter_by(life_event_id=story["car"].id).one()
    plan = get_or_create_default_plan(db, 1)
    legacy = models.MonthlyPlanLine(client_id=1, plan_id=plan.id, target_period=START, line_type="allocation",
                                    target_type="capsule", target_id=car_capsule.id, amount_minor=500)
    db.add(legacy)
    db.commit()
    capsule_service.set_funding_sources(db, 1, car_capsule.id, [
        schemas.CapsuleFundingSourceInput(account_id=story["savings"].id, target_amount=1),
        schemas.CapsuleFundingSourceInput(account_id=story["other"].id, target_amount=1, sort_order=1),
    ])
    chosen = options()
    preview = workflow.preview(db, 1, chosen)
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    rows = plan_lines(db, target_period=START, target_type="capsule")
    assert sorted((line.account_id, line.amount) for line in rows) == [(story["savings"].id, 5000), (story["other"].id, 5000)]
    db.refresh(legacy)
    assert legacy.is_active is False


def test_a_definition_destination_also_updates_saved_months(db, story):
    from app.services.budget_plan_store import create_plan_lines
    definition, yearly, _ = existing_savings(db, story)
    create_plan_lines(db, 1, [{"target_period": START, "line_type": "allocation", "target_type": "account",
                               "account_id": story["savings"].id, "amount": 20000}])
    chosen = options(savings_definition_id=definition.id)
    preview = workflow.preview(db, 1, chosen)
    saved = next(row for row in preview["changes"] if row["kind"] == "definition_row")
    assert (saved["current_amount"], saved["new_amount"]) == (20000, 23000)
    assert preview["savings"]["definition_differences"] == []
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    assert [line.amount for line in plan_lines(db, target_period=START, account_id=story["savings"].id)] == [23000]


def test_a_definition_destination_takes_the_first_months_rest(db, story):
    definition, _, _ = existing_savings(db, story)
    chosen = options(savings_definition_id=definition.id, months=2)
    preview = workflow.preview(db, 1, chosen)
    # The yearly definition is saved only in November, so December's own rest is 12,000
    # larger; the definition holds one amount, November's, and shows the difference.
    change = next(row for row in preview["changes"] if row["kind"] == "definition")
    assert change["new_amount"] == 23000
    assert preview["savings"]["definition_differences"] == [{"period": "2026-12", "difference": -12000}]
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    db.refresh(definition)
    assert definition.amount == 23000


def short_savings(db, story, amount):
    from app.services import life_scenario_service
    life_scenario_service.update(db, 1, story["car"].scenario_id, {"monthly_savings": amount})


def capsule_rows(preview):
    return {row["name"]: row["new_amount"] for row in preview["changes"] if row["kind"] == "capsule"}


def test_a_shortfall_cuts_the_groups_at_the_end_of_the_funding_order(db, story):
    consumable(db, story)
    short_savings(db, story, 10500)
    # Default order: products are funded in full and the car's capsule is cut.
    first = workflow.preview(db, 1, options(savings_account_id=story["savings"].id))
    assert capsule_rows(first) == {"車の取り置き": 9500, "日用品": 1000}
    assert first["savings"]["groups"] == [
        {"key": "existing", "need": 0, "amount": 0}, {"key": "products", "need": 1000, "amount": 1000},
        {"key": "near", "need": 10000, "amount": 9500}]
    assert next(row for row in first["events"] if row["name"] == "車")["allocation"] == 9500
    # Near events first: the car is funded and the product reserve is cut instead.
    near_first = options(savings_account_id=story["savings"].id, funding_order=["near", "existing", "products"])
    second = workflow.preview(db, 1, near_first)
    assert capsule_rows(second) == {"車の取り置き": 10000, "日用品": 500}
    assert second["savings"]["shortfall"] == 500 and second["savings"]["account_amount"] == 0
    assert second["options"]["funding_order"] == ["near", "existing", "products"]
    # The order is part of what is confirmed.
    with pytest.raises(Conflict):
        workflow.apply(db, 1, near_first, first["fingerprint"])


def test_existing_savings_ordered_last_are_counted_less_but_never_rewritten(db, story):
    existing_savings(db, story)
    short_savings(db, story, 40000)
    before = workflow.preview(db, 1, options(savings_account_id=story["savings"].id))
    # Existing 37,000 first: the car gets the 3,000 left.
    assert (before["savings"]["existing_amount"], before["savings"]["capsule_amount"]) == (37000, 3000)
    chosen = options(savings_account_id=story["savings"].id, funding_order=["near", "products", "existing"])
    after = workflow.preview(db, 1, chosen)
    groups = {row["key"]: row for row in after["savings"]["groups"]}
    assert (groups["existing"]["need"], groups["existing"]["amount"]) == (37000, 30000)
    assert (after["savings"]["capsule_amount"], after["savings"]["account_amount"]) == (10000, 0)
    # Only the goal's own rows are written; the definitions and the loose capsule stay as they are.
    assert {row["kind"] for row in after["changes"]} <= {"capsule", "savings"}
    assert capsule_rows(after) == {"車の取り置き": 10000}
    workflow.apply(db, 1, chosen, after["fingerprint"])
    record = db.query(models.GoalBudgetReflection).one()
    assert record.options["funding_order"] == ["near", "products", "existing"]
    assert record.summary["groups"][-1] == {"key": "existing", "need": 37000, "amount": 30000}


def test_progress_and_breakdown_follow_the_latest_funding_order(db, story):
    from app.services.strategy_service import event_monthly_allocation
    consumable(db, story)
    short_savings(db, story, 10500)
    chosen = options(savings_account_id=story["savings"].id, funding_order=["near", "existing", "products"])
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    covered = {row["name"]: row for row in workflow.status(db, 1, START)["events"]}
    assert (covered["車"]["allocation"], covered["車"]["source"]) == (10000, "reflection")
    assert (covered["日用品"]["allocation"], covered["日用品"]["source"]) == (500, "reflection")
    # A later month is divided by the rule, still near events first: they need more
    # than the 10,500, so they share all of it and the product reserve gets nothing.
    assert event_monthly_allocation(db, 1, story["car"], 10500, date(2027, 1, 1))[1] == "rule"
    later = {row["name"]: row for row in workflow.status(db, 1, "2027-01")["events"]}
    near = sum(row["allocation"] for row in later.values() if row["kind"] == "near")
    assert near == pytest.approx(10500, abs=0.05)
    assert (later["日用品"]["allocation"], later["日用品"]["source"]) == (0, "rule")
    assert all(row["allocation"] == 0 for row in later.values() if row["kind"] == "far")


def test_the_funding_order_lists_every_group_once():
    with pytest.raises(ValueError):
        schemas.GoalBudgetOptions(start_period=START, funding_order=["near", "near", "products"])
    assert schemas.GoalBudgetOptions(start_period=START).funding_order is None


def test_a_zero_definition_destination_stays_selectable(db, story):
    definition, _, _ = existing_savings(db, story)
    definition.amount_minor = 0
    db.commit()
    preview = workflow.preview(db, 1, options(savings_definition_id=definition.id))
    assert next(row for row in preview["existing"] if row["kind"] == "definition" and row["id"] == definition.id)["destination"]


def test_apply_writes_into_the_plan_the_preview_read(db, story):
    from app.services.budget_plan_store import create_plan
    only = create_plan(db, 1, {"name": "家計"})
    chosen = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    assert db.query(models.BudgetPlan).count() == 1
    assert {line.plan_id for line in plan_lines(db)} == {only.id}


def test_changing_priorities_changes_the_fingerprint(db, story):
    second = add_event(db, "老後", date(2050, 1, 1), 5_000_000, priority=3)
    chosen = options()
    before = workflow.preview(db, 1, chosen)
    story["home"].priority, second.priority = 3, 1
    db.commit()
    with pytest.raises(Conflict):
        workflow.apply(db, 1, chosen, before["fingerprint"])


def test_overlapping_reflections_count_each_month_once_for_the_handover(db, story):
    chosen = options(savings_account_id=story["savings"].id, months=3)
    for _ in range(2):
        workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    home = next(row for row in workflow.preview(db, 1, chosen)["events"] if row["name"] == "住宅")
    near = next(row for row in workflow.status(db, 1, "2042-01")["reminders"] if row["code"] == "event_near")
    assert near["handover_amount"] == pytest.approx(home["allocation"] * 3)


def test_progress_uses_the_reflection_of_its_own_month_and_never_funds_archived_events(db, story):
    from datetime import datetime
    from app.services.strategy_service import event_monthly_allocation
    chosen = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    car = story["car"]
    assert event_monthly_allocation(db, 1, car, 50000, date(2026, 11, 1)) == (10000, "reflection")
    # A month the reflection does not cover is divided by the rule.
    assert event_monthly_allocation(db, 1, car, 50000, date(2027, 3, 1))[1] == "rule"
    car.archived_at = datetime(2026, 11, 2)
    db.commit()
    assert event_monthly_allocation(db, 1, car, 50000, date(2026, 11, 1)) == (0.0, "rule")



def fund(db, account, amount):
    from app.services.ledger_service import create_transaction
    salary = create_account(db, 1, {"name": f"給与{account.id}", "account_type": "income"})
    create_transaction(db, client_id=1, date=date(2026, 10, 1), description="入金", amount_minor=amount,
                       currency="JPY", from_account_id=salary.id, to_account_id=account.id)
    db.commit()


def far_then_near(db, story):
    """Three months reflected while the home was far, then a reflection after it becomes near."""
    first = options(savings_account_id=story["savings"].id, months=3)
    preview = workflow.preview(db, 1, first)
    home_far = next(row for row in preview["events"] if row["name"] == "住宅")["allocation"]
    workflow.apply(db, 1, first, preview["fingerprint"])
    near = options(savings_account_id=story["savings"].id, start_period="2042-01", create_capsules=[story["home"].id])
    return home_far, near


def test_a_handover_is_suggested_when_a_far_event_becomes_near(db, story):
    fund(db, story["savings"], 5_000_000)
    home_far, near = far_then_near(db, story)
    preview = workflow.preview(db, 1, near)
    suggestion = next(row for row in preview["handover_suggestions"] if row["name"] == "住宅")
    # Three months of its far share, from the savings account of the earlier reflection.
    assert suggestion["planned"] == pytest.approx(home_far * 3)
    assert suggestion["suggested"] == pytest.approx(home_far * 3)
    assert suggestion["account_id"] == story["savings"].id
    assert preview["handovers"] == []  # nothing is claimed until the user confirms it


def test_a_confirmed_handover_claims_savings_and_lowers_the_monthly_amount(db, story):
    fund(db, story["savings"], 5_000_000)
    _, near = far_then_near(db, story)
    without = next(row for row in workflow.preview(db, 1, near)["events"] if row["name"] == "住宅")
    chosen = near | {"handovers": [{"event_id": story["home"].id, "account_id": story["savings"].id, "amount": 600_000}]}
    preview = workflow.preview(db, 1, chosen)
    handover = preview["handovers"][0]
    assert (handover["funded_before"], handover["funded_after"]) == (0, 600_000)
    assert handover["available_before"] - handover["available_after"] == 600_000
    assert handover["adds_funding_source"] is True
    assert handover["monthly_after"] < handover["monthly_before"] == without["monthly_required"]
    home = next(row for row in preview["events"] if row["name"] == "住宅")
    assert home["monthly_required"] == handover["monthly_after"]
    claim = next(row for row in preview["changes"] if row["kind"] == "claim")
    assert (claim["current_amount"], claim["new_amount"]) == (0, 600_000)
    workflow.apply(db, 1, chosen, preview["fingerprint"])
    capsule = db.query(models.Capsule).filter_by(life_event_id=story["home"].id).one()
    assert capsule_service.claimed_minor(db, 1, capsule.id, story["savings"].id) == {"JPY": 600_000}
    assert [source.account_id for source in capsule.funding_sources] == [story["savings"].id]
    # Handed-over savings are not suggested again.
    again = workflow.preview(db, 1, near | {"create_capsules": []})
    remaining = next((row for row in again["handover_suggestions"] if row["name"] == "住宅"), None)
    assert remaining is None or remaining["planned"] < 600_000


@pytest.mark.parametrize("amount, message", [(6_000_000, "確保できる残高"), (20_000_000, "不足を超えて")])
def test_a_handover_cannot_exceed_the_unclaimed_balance_or_the_need(db, story, amount, message):
    fund(db, story["savings"], 5_000_000)
    _, near = far_then_near(db, story)
    chosen = near | {"handovers": [{"event_id": story["home"].id, "account_id": story["savings"].id, "amount": amount}]}
    with pytest.raises(Refused, match=message):
        workflow.preview(db, 1, chosen)


def test_reasons_become_one_notification_and_the_reflection_answers_it(db, story):
    from app.workflows import notification_workflow

    def reflections(listing):
        return [row for row in listing["items"] if row["kind"] == "goal_reflection"]
    first = notification_workflow.sync(db, 1, START)
    again = notification_workflow.sync(db, 1, START)
    assert [row["id"] for row in first["items"]] == [row["id"] for row in again["items"]]
    (note,) = reflections(again)
    assert (note["status"], note["link"]) == ("open", "/goals")
    assert note["payload"]["reminders"][0]["code"] == "never"
    chosen = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    assert db.get(models.Notification, note["id"]).status == "done"
    assert reflections(notification_workflow.listing(db, 1)) == []


def consumable(db, story):
    """A consumable reserving 6,000 every 180 days (1,000 a month) into its own capsule."""
    from app.workflows import product_workflow
    pool = capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="日用品", target_amount=0, monthly_contribution=0,
                                                                        account_id=story["other"].id))
    confirmed(product_workflow.create_product, db, 1, schemas.ProductCreate(
        name="浄水フィルター", last_unit_price=6000, frequency_days=180, funding_capsule_id=pool.id,
        budget_treatment="reserve_allocation"))
    return pool


def test_product_reserves_are_part_of_the_reflection(db, story):
    pool = consumable(db, story)
    preview = workflow.preview(db, 1, options(savings_account_id=story["savings"].id))
    assert preview["products"] == [{"capsule_id": pool.id, "name": "日用品", "products": 1, "monthly": 1000}]
    savings = preview["savings"]
    assert (savings["product_amount"], savings["account_amount"]) == (1000, 39000)
    # Written as the capsule's row, and not also counted as existing savings.
    rows = [(row["kind"], row["name"], row["new_amount"]) for row in preview["changes"]]
    assert ("capsule", "日用品", 1000) in rows
    assert all(row["key"] != f"capsule:{pool.id}" for row in preview["existing"])
    status = workflow.status(db, 1, START)
    product = next(row for row in status["events"] if row["kind"] == "product")
    assert (product["name"], product["allocation"]) == ("日用品", 1000)


def test_progress_shares_what_is_left_after_product_reserves(db, story):
    from app.services.strategy_service import event_monthly_allocation
    home = story["home"]
    before, _ = event_monthly_allocation(db, 1, home, 50000, date(2026, 11, 1))
    consumable(db, story)
    after, _ = event_monthly_allocation(db, 1, home, 50000, date(2026, 11, 1))
    assert before - after == pytest.approx(1000)


def test_one_handover_per_event(db, story):
    fund(db, story["savings"], 5_000_000)
    _, near = far_then_near(db, story)
    line = {"event_id": story["home"].id, "account_id": story["savings"].id, "amount": 100_000}
    # Each line alone fits the shortfall; together they would claim twice.
    with pytest.raises(Refused, match="1件"):
        workflow.preview(db, 1, near | {"handovers": [line, line]})


def test_handover_suggestions_share_the_account_balance(db, story):
    school = add_event(db, "教育", date(2045, 4, 1), 8_000_000)
    fund(db, story["savings"], 10_000)
    _, near = far_then_near(db, story)
    preview = workflow.preview(db, 1, near | {"create_capsules": [story["home"].id, school.id]})
    suggested = [row["suggested"] for row in preview["handover_suggestions"]]
    assert len(suggested) == 2 and sum(suggested) == 10_000
    # Taking every suggestion is therefore a valid choice.
    picks = [{"event_id": row["event_id"], "account_id": row["account_id"], "amount": row["suggested"]}
             for row in preview["handover_suggestions"] if row["suggested"] > 0]
    workflow.preview(db, 1, near | {"create_capsules": [story["home"].id, school.id], "handovers": picks})


def test_a_fixed_asset_reserve_is_read_for_each_month(db, story):
    from app.services.product_reserve_service import product_reserve_values
    from app.workflows import product_workflow
    pool = capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="家電", target_amount=0, monthly_contribution=0,
                                                                        account_id=story["other"].id))
    product = confirmed(product_workflow.create_product, db, 1, schemas.ProductCreate(
        name="冷蔵庫", last_unit_price=120000, purchase_price=120000, is_asset=True, purchase_date=date(2026, 10, 1),
        lifespan_months=24, funding_capsule_id=pool.id))
    preview = workflow.preview(db, 1, options(savings_account_id=story["savings"].id, months=2))
    rows = {row["period"]: row["new_amount"] for row in preview["changes"] if row["capsule_id"] == pool.id}
    expected = {period: product_reserve_values(product, date(int(period[:4]), int(period[5:]), 1), "JPY")["recommended_monthly_reserve"]
                for period in ("2026-11", "2026-12")}
    assert rows == expected and expected["2026-11"] < expected["2026-12"]


def test_a_budget_row_does_not_overwrite_what_products_set(db, story):
    from types import SimpleNamespace
    from app.services import budget_plan_store
    pool = consumable(db, story)
    line = SimpleNamespace(target_type="capsule", target_id=pool.id, plan_id=None, target_period=START, line_type="allocation")
    budget_plan_store.sync_capsule_monthly_contributions(db, 1, [line])
    db.refresh(pool)
    assert (pool.monthly_contribution_source, pool.monthly_contribution) == ("linked_products", 1000)


@pytest.mark.parametrize("currency, monthly", [("USD", 0.2), ("JPY", 0.0)])
def test_reserves_round_to_the_currency_minor_unit(currency, monthly):
    from types import SimpleNamespace
    from app.services.product_reserve_service import product_reserve_values
    product = SimpleNamespace(budget_treatment="reserve_allocation", is_asset=False, units_per_purchase=1,
                              last_unit_price=0.4, frequency_days=60)
    assert product_reserve_values(product, currency=currency)["recommended_monthly_reserve"] == monthly


def test_a_goal_that_fails_part_way_is_not_saved(db, monkeypatch):
    from app.workflows import goal_workflow

    def broken(*_args, **_kwargs):
        raise RuntimeError("milestones failed")
    monkeypatch.setattr(goal_workflow, "build_default_milestone_rows", broken)
    payload = schemas.LifeEventCreate(scenario_id=goal_scenario_id(db, 1), name="途中で失敗", target_date=date(2030, 1, 1),
                                      target_amount=100000)
    with pytest.raises(RuntimeError):
        goal_workflow.create_goal(db, 1, payload)
    db.rollback()
    assert db.query(models.LifeEvent).filter_by(name="途中で失敗").count() == 0


def needs(check):
    return {group["key"]: group["need"] for group in check["groups"]}


def test_savings_check_compares_the_budget_with_every_monthly_need(db, api, story):
    _, _, loose = existing_savings(db, story)
    consumable(db, story)
    check = workflow.savings_check(db, 1, START)
    # 37,000 the user put in the budget, 1,000 products, the car's 10,000; the goal's
    # 50,000 leaves 2,000 for its own row. Each is counted once, so the need is 50,000.
    assert needs(check) == {"existing": 37000, "products": 1000, "near": 10000, "rest": 2000}
    assert check["need"] == 50000 and check["goal"]["monthly_savings"] == 50000
    assert check["budgeted"] == workflow.status(db, 1, START)["budget"]["total"]
    assert check["shortfall"] == 50000 - check["budgeted"] > 0
    near = next(group for group in check["groups"] if group["key"] == "near")
    assert near["items"] == [{"name": "車", "amount": 10000}]
    # The reflected budget holds exactly the need.
    chosen = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    after = request(api, "GET", "/goal-budget/savings-check", params={"period": START}).json()
    assert (after["budgeted"], after["need"], after["shortfall"]) == (50000, 50000, 0)
    # Savings the reflection does not count still need their budget row; the goal's rest grows.
    uncounted = options(savings_account_id=story["savings"].id, uncounted=[f"capsule:{loose.id}"])
    workflow.apply(db, 1, uncounted, workflow.preview(db, 1, uncounted)["fingerprint"])
    later = workflow.savings_check(db, 1, START)
    assert needs(later)["existing"] == 37000 and needs(later)["rest"] == 7000
    assert (later["budgeted"], later["shortfall"]) == (55000, 0)


def test_savings_check_shows_what_a_cut_reflection_leaves_short(db, story):
    consumable(db, story)
    short_savings(db, story, 10500)
    chosen = options(savings_account_id=story["savings"].id)
    workflow.apply(db, 1, chosen, workflow.preview(db, 1, chosen)["fingerprint"])
    check = workflow.savings_check(db, 1, START)
    assert needs(check) == {"existing": 0, "products": 1000, "near": 10000, "rest": 0}
    assert (check["budgeted"], check["need"], check["shortfall"]) == (10500, 11000, 500)


def test_savings_check_without_a_goal_needs_the_products_and_the_budgets_own_savings(db):
    other = create_account(db, 1, {"name": "別の口座", "account_type": "asset"})
    db.commit()
    consumable(db, {"other": other})
    check = workflow.savings_check(db, 1, START)
    assert check["goal"] is None
    assert needs(check) == {"existing": 0, "products": 1000, "near": 0, "rest": 0}
    assert check["shortfall"] == 1000 - check["budgeted"]
