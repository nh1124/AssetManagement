"""WP27: 計画への反映 -- the goal and the product earmarks written into the plan, by itself or when asked."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import models, schemas
from app.database import get_db
from app.dependencies import get_current_client
from app.domain.errors import DomainError, Invalid, detail_for, status_for
from app.domain.journal import Leg
from app.routers.plan_reflection import router as reflection_router
from app.routers.life_scenarios import router as scenarios_router
from app.services import client_settings_service, goal_budget_record, goal_plan_service, goal_service
from app.services import contribution_plan_service as plans
from app.services.goal_plan_service import earmark_rows
from app.services.ledger_service import create_transaction
from app.services.product_reserve_service import refresh_product_capsules
from app.workflows import notification_workflow, plan_reflection_workflow as reflection
from scenario_fixtures import account, db, request  # noqa: F401

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")
FIRST = TODAY.year * 12 + TODAY.month - 1


def month(offset: int) -> str:
    index = FIRST + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_date(offset: int) -> date:
    index = FIRST + offset
    return date(index // 12, index % 12 + 1, 1)


def goal(db):
    scenario = models.LifeScenario(client_id=1, name="ゴール", is_goal=True, annual_return=0, inflation=0, horizon_years=3)
    db.add(scenario)
    db.commit()
    return scenario


def trip(db, scenario, savings, amount=120000, months=12):
    """A trip `months` ahead, paid from savings in one withdrawal: its earmark holds `amount` until then."""
    event = goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(
        scenario_id=scenario.id, name="旅行", target_amount=amount, target_date=month_date(months)))
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": month(months), "kind": "withdrawal",
                                            "amount": amount, "life_event_id": event.id})
    return event


def settings(db, **patch):
    return client_settings_service.merge_reflection_settings(db, db.get(models.Client, 1), patch, period=PERIOD)


def rows(db, kind=None):
    query = db.query(models.MonthlyPlanLine).filter_by(client_id=1, is_active=True)
    lines = [line for line in query.order_by(models.MonthlyPlanLine.target_period).all()
             if kind is None or (line.target_type == "capsule") == (kind == "capsule")]
    return [(line.target_period, line.amount_minor) for line in lines]


OPTIONS = {"base": "remaining", "held": "even", "catch_up": "even"}


@pytest.mark.parametrize("options, expected", [
    # 残り期間に合わせる: (120,000 − 30,000) over 6 months, or 20,000 a month with the 30,000 off the nearest months.
    ({}, [15000] * 6),
    ({"held": "recent"}, [0, 10000, 20000, 20000, 20000, 20000]),
    # 積立設定から決まる額: 120,000 over the 12 months since the earmark began is 10,000; 6 have passed, 60,000 expected.
    # Holding 30,000 is 30,000 behind: spread over the 6 left, added to this month, or not caught up.
    ({"base": "goal_setting"}, [15000] * 6),
    ({"base": "goal_setting", "catch_up": "recent"}, [40000] + [10000] * 5),
    ({"base": "goal_setting", "catch_up": "none"}, [10000] * 6),
])
def test_an_earmarks_rows_follow_the_base_the_held_amount_and_the_catch_up(options, expected):
    assert earmark_rows(120000, 30000, first=106, current=100, started=94, options={**OPTIONS, **options}) == expected


def test_holding_more_than_the_schedule_takes_the_surplus_off_as_chosen():
    ahead = {**OPTIONS, "base": "goal_setting"}
    # 6 of 12 months passed (60,000 expected) and 80,000 held: 20,000 comes off.
    assert earmark_rows(120000, 80000, 106, 100, 94, ahead) == [6667, 6667, 6667, 6667, 6666, 6666]
    assert earmark_rows(120000, 80000, 106, 100, 94, {**ahead, "held": "recent"}) == [0, 0, 10000, 10000, 10000, 10000]
    # In the withdrawal month itself the rest comes at once; after it, nothing.
    assert earmark_rows(120000, 100000, 100, 100, 94, OPTIONS) == [20000]
    assert earmark_rows(120000, 100000, 99, 100, 94, OPTIONS) == []


def test_settings_are_checked_and_since_is_the_month_they_were_first_saved(db):
    saved = settings(db, goal={"base": "goal_setting"})
    assert (saved["enabled"], saved["goal"], saved["since"]) == (False, {"base": "goal_setting", "held": "even", "catch_up": "even"}, PERIOD)
    with pytest.raises(Invalid):
        settings(db, goal={"catch_up": "later"})
    assert client_settings_service.reflection_settings(db.get(models.Client, 1))["goal"]["base"] == "goal_setting"


def test_a_run_writes_twelve_months_and_turning_it_on_writes_at_once(db):
    scenario, savings = goal(db), account(db, "貯蓄")
    trip(db, scenario, savings)
    assert rows(db) == []
    result = reflection.save_settings(db, 1, {"enabled": True})
    # Turning 自動反映 on rewrote this month and the 11 after it: the earmark's 12 rows of 10,000.
    assert result["run"]["changes"] == 12
    assert rows(db, "capsule") == [(month(offset), 10000) for offset in range(12)]
    assert reflection.settings(db, 1)["last_period"] == PERIOD
    # Nothing changed, so the start-of-month run waits for next month and a change run writes nothing.
    assert reflection.run_due(db, 1) is None
    reflection.after_change(db, 1)
    assert [row["trigger"] for row in goal_budget_record.history(db, 1)] == ["settings"]


def test_after_a_change_the_plan_follows_only_while_automatic(db):
    scenario, savings = goal(db), account(db, "貯蓄")
    event = trip(db, scenario, savings)
    reflection.after_change(db, 1)
    assert rows(db) == []
    settings(db, enabled=True)
    goal_service.update_goal(db, 1, event.id, schemas.LifeEventUpdate(target_amount=240000))
    plans.update_plan(db, 1, plans.list_plans(db, 1, scenario.id)[0].id, {"amount": 240000})
    reflection.after_change(db, 1)
    assert set(amount for _, amount in rows(db, "capsule")) == {20000}
    assert goal_budget_record.history(db, 1)[0]["trigger"] == "change"


def test_the_start_of_month_run_happens_once_a_month(db):
    scenario, savings = goal(db), account(db, "貯蓄")
    trip(db, scenario, savings)
    settings(db, enabled=True, last_period=month(-1))
    assert reflection.run_due(db, 1)["trigger"] == "month"
    assert reflection.run_due(db, 1) is None
    # The daily loop visits only the clients that turned it on.
    assert client_settings_service.reflection_client_ids(db) == [1]


def test_a_shortfall_of_contributions_since_the_settings_began_is_caught_up(db):
    scenario, savings = goal(db), account(db, "貯蓄")
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": month(-3), "amount": 30000})
    income = account(db, "給与", kind="income")
    # Three months of 30,000 were due; 60,000 came in.
    create_transaction(db, client_id=1, date=month_date(-2), description="積立", amount_minor=60000, currency="JPY",
                       from_account_id=income.id, to_account_id=savings.id)
    db.commit()
    for catch_up, first, later in (("even", 32500, 32500), ("recent", 60000, 30000), ("none", 30000, 30000)):
        settings(db, goal={"catch_up": catch_up})
        client = db.get(models.Client, 1)
        client.general_settings = {**client.general_settings, "plan_reflection": {**client.general_settings["plan_reflection"], "since": month(-3)}}
        db.commit()
        reflection.run(db, 1, "manual")
        accounts = [amount for period, amount in rows(db) if period in (month(0), month(1))]
        assert accounts == [first, later], catch_up


def test_an_automatic_run_is_announced_and_the_reminder_stops(db):
    scenario, savings = goal(db), account(db, "貯蓄")
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "amount": 30000})
    assert goal_plan_service.reflection_notifications(db, 1, PERIOD) != []
    reflection.save_settings(db, 1, {"enabled": True})
    assert goal_plan_service.reflection_notifications(db, 1, PERIOD) == []
    (item,) = notification_workflow.GENERATORS[goal_budget_record.REFLECTED_NOTIFICATION](db, 1, PERIOD)
    assert item["title"] == "計画を自動で更新しました" and "12件の行を変更しました（設定の保存）" in item["body"]
    # 今すぐ反映 is the user's own act: nothing to announce.
    reflection.run(db, 1, "manual")
    assert notification_workflow.GENERATORS[goal_budget_record.REFLECTED_NOTIFICATION](db, 1, PERIOD) == []


def test_product_earmarks_are_written_unless_turned_off(db):
    savings = account(db, "貯蓄")
    capsule = models.Capsule(client_id=1, name="家電", target_amount_minor=0, monthly_contribution_minor=0,
                             funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=savings.id, target_amount_minor=120000)])
    db.add(capsule)
    db.flush()
    db.add(models.Product(client_id=1, name="冷蔵庫", is_asset=True, purchase_price_minor=120000, purchase_date=month_date(-2), lifespan_months=12,
                          funding_capsule_id=capsule.id))
    db.flush()
    refresh_product_capsules(db, 1, [capsule.id])
    db.commit()
    settings(db, products={"enabled": False})
    reflection.run(db, 1, "manual")
    assert rows(db, "capsule") == []
    settings(db, products={"enabled": True})
    preview = reflection.preview(db, 1)
    # Replaced in 10 months: 120,000 over them.
    assert {(row["origin"], row["new"]) for row in preview["changes"]} == {("products", 12000)}
    reflection.run(db, 1, "manual")
    assert rows(db, "capsule") == [(month(offset), 12000) for offset in range(10)]


@pytest.fixture
def api(db):
    app = FastAPI()
    for router in (reflection_router, scenarios_router):
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})
    return app


def test_http_settings_preview_run_and_changes_follow(db, api):
    scenario, savings = goal(db), account(db, "貯蓄")
    trip(db, scenario, savings)
    shown = request(api, "GET", "/plan/reflection").json()
    assert (shown["settings"]["enabled"], shown["periods"][0], len(shown["periods"]), shown["history"]) == (False, PERIOD, 12, [])
    preview = request(api, "POST", "/plan/reflection/preview", json={"goal": {"held": "recent"}}).json()
    assert len(preview["changes"]) == 12 and preview["settings"]["goal"]["held"] == "recent"
    assert rows(db) == []
    assert request(api, "PUT", "/plan/reflection/settings", json={"goal": {"base": "sometime"}}).status_code == 422
    assert request(api, "POST", "/plan/reflection/run").json()["changes"] == 12
    # With 自動反映 on, adding a 積立 through the API rewrites the plan at once.
    request(api, "PUT", "/plan/reflection/settings", json={"enabled": True})
    request(api, "POST", f"/life-scenarios/{scenario.id}/contribution-plans", json={"account_id": savings.id, "start_period": PERIOD, "amount": 30000})
    assert (PERIOD, 30000) in rows(db, "account")
    history = request(api, "GET", "/plan/reflection").json()["history"]
    assert [row["trigger"] for row in history] == ["change", "manual"]


def test_held_money_counts_toward_the_earmark(db):
    scenario, savings = goal(db), account(db, "貯蓄", balance=100000)
    event = trip(db, scenario, savings)
    reflection.run(db, 1, "manual")
    capsule = db.query(models.Capsule).filter_by(goal_event_id=event.id).one()
    create_transaction(db, client_id=1, date=TODAY, description="確保", amount_minor=24000, currency="JPY",
                       legs=[Leg(savings.id, debit=24000, capsule_id=capsule.id), Leg(savings.id, credit=24000)])
    db.commit()
    reflection.run(db, 1, "manual")
    # (120,000 − 24,000) over the 12 months.
    assert set(amount for _, amount in rows(db, "capsule")) == {8000}
