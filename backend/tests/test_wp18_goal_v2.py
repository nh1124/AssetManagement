"""WP18: loans in life events, withdrawals in 積立設定, goal-derived earmarks and changing the goal (R11)."""
from datetime import date
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import models, schemas
from app.domain.errors import NotFound, Refused
from app.domain.journal import Leg
from app.domain.transfer import migrate_goal_v2
from app.services import capsule_service
from app.services import contribution_plan_service as plans
from app.services import goal_earmark_service, goal_service, life_scenario_service as scenarios
from app.services.ledger_service import create_transaction
from app.workflows import goal_budget_workflow, goal_change_workflow
from scenario_fixtures import account, db  # noqa: F401

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")


def in_years(years: int, month: int = 1) -> date:
    return date(TODAY.year + years, month, 1)


def months_ahead(months: int) -> date:
    index = TODAY.year * 12 + TODAY.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def goal(db, name="ゴール"):
    scenario = models.LifeScenario(client_id=1, name=name, is_goal=True, annual_return=0, inflation=0, horizon_years=3)
    db.add(scenario)
    db.commit()
    return scenario


def still(db):
    db.add(models.SimulationConfig(client_id=1, volatility=0, tax_rate=0))
    db.commit()


def create(db, scenario, name, amount, when, account_id=None, **values):
    row = goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(
        scenario_id=scenario.id, name=name, target_amount=amount, target_date=when, **values))
    if account_id is not None and row.direction == "expense":
        # ライフイベントへの取り崩し (WP22): the account withdraws the whole amount in the event's month.
        plans.create_plan(db, 1, scenario.id, {"account_id": account_id, "start_period": when.strftime("%Y-%m"),
                                                "monthly_amount": -amount, "life_event_id": row.id})
    return row


def test_an_event_works_through_an_asset_account_and_a_repayment_names_a_borrowing(db):
    scenario = goal(db)
    savings, food = account(db, "貯蓄"), account(db, "食費", kind="expense")
    with pytest.raises(Refused):
        create(db, scenario, "外食", 1000, in_years(1), account_id=food.id)
    loan = create(db, scenario, "住宅ローン", 3_000_000, in_years(1), direction="borrowing", account_id=savings.id, interest_rate=1.5)
    assert (loan.interest_rate, loan.repeat_count) == (1.5, None)
    with pytest.raises(Refused):
        create(db, scenario, "返済", 50000, in_years(1), direction="repayment")
    repay = create(db, scenario, "返済", 50000, in_years(1), direction="repayment", borrowing_event_id=loan.id, repeat_count=60)
    trip = create(db, scenario, "旅行", 100000, in_years(1), interest_rate=9, repeat_count=3)
    # What a kind does not use is cleared.
    assert (trip.interest_rate, trip.repeat_count, trip.borrowing_event_id) == (None, None, None)
    with pytest.raises(Refused):
        goal_service.update_goal(db, 1, loan.id, schemas.LifeEventUpdate(direction="expense"))
    # A copied story repays the copy of its borrowing.
    copy = scenarios.duplicate(db, 1, scenario.id, "複製")
    copied = {row.name: row for row in db.query(models.LifeEvent).filter_by(scenario_id=copy.id)}
    assert copied["返済"].borrowing_event_id == copied["住宅ローン"].id != loan.id
    assert repay.borrowing_event_id == loan.id
    other = scenarios.create(db, 1, "別")
    with pytest.raises(Refused):
        create(db, other, "返済", 1, in_years(1), direction="repayment", borrowing_event_id=loan.id)


def test_a_loan_moves_cash_and_debt_together_and_its_repayments_pay_interest_first(db):
    still(db)
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=1_000_000)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "annual_return": 0})
    loan = create(db, scenario, "ローン", 1_200_000, in_years(1), direction="borrowing", account_id=savings.id, interest_rate=12)
    create(db, scenario, "返済", 100000, in_years(1), direction="repayment", borrowing_event_id=loan.id, repeat_count=12, account_id=savings.id)
    result = scenarios.project(db, 1, scenario)
    # 1% a month on what is left: after twelve payments 83,940 of the debt remains.
    debt = 1_200_000 * 1.01 ** 12 - 100000 * (1.01 ** 12 - 1) / 0.01
    assert result["projection"][1]["p50"] == pytest.approx(1_000_000 - debt, abs=1)
    assert result["accounts"][0]["p50"][1] == pytest.approx(1_000_000 + 1_200_000 - 1_200_000, abs=1)
    by_name = {row["name"]: row for row in result["events"]}
    assert by_name["ローン"]["funded_probability"] is None and by_name["返済"]["executed_probability"] == 1.0


def test_repayments_happen_only_where_their_borrowing_did(db):
    still(db)
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=500_000)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "annual_return": 0})
    loan = create(db, scenario, "ローン", 1_000_000, in_years(1), direction="borrowing", account_id=savings.id)
    db.add(models.LifeEventCondition(client_id=1, life_event_id=loan.id, metric="net_worth", comparator="gte", threshold_minor=10**12))
    db.commit()
    create(db, scenario, "返済", 50000, in_years(1), direction="repayment", borrowing_event_id=loan.id, repeat_count=12)
    result = scenarios.project(db, 1, scenario)
    assert {row["name"]: row["executed_probability"] for row in result["events"]} == {"ローン": 0.0, "返済": 0.0}
    assert result["projection"][-1]["p50"] == 500_000


def test_only_used_accounts_grow_and_a_negative_record_withdraws(db):
    still(db)
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=600_000)
    cash = account(db, "現金", balance=100_000)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "monthly_amount": -10000, "annual_return": 0})
    result = scenarios.project(db, 1, scenario)
    assert [row["account_id"] for row in result["accounts"]] == [savings.id]
    assert result["accounts"][0]["p50"][:3] == [600_000, 480_000, 360_000]
    # The unused cash stays in the rest of net worth.
    assert result["projection"][1]["p50"] == 580_000
    assert result["monthly_contribution"] == -10000
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    assert [(row["kind"], row["new"]) for row in preview["changes"]] == [("drawdown", 10000)]
    goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])
    line = db.query(models.MonthlyPlanLine).filter_by(client_id=1, source_kind="goal", is_active=True).one()
    assert (line.line_type, line.target_type, line.account_id, line.amount_minor) == ("drawdown", "account", savings.id, 10000)
    assert cash.id not in {row["account_id"] for row in result["accounts"]}


def _funded_goal(db):
    """A goal whose event already has its earmark holding 40000, and a copy of that story."""
    scenario = goal(db, "基本")
    savings = account(db, "貯蓄", balance=500_000)
    trip = create(db, scenario, "旅行", 100000, months_ahead(10), account_id=savings.id)
    only = create(db, scenario, "車", 50000, months_ahead(10), account_id=savings.id)
    capsule = capsule_service.create_goal_capsule(db, 1, event_id=trip.id, name="旅行", target_minor=100000, parts={savings.id: 100000})
    lone = capsule_service.create_goal_capsule(db, 1, event_id=only.id, name="車", target_minor=50000, parts={savings.id: 50000})
    create_transaction(db, client_id=1, date=TODAY, description="確保", amount_minor=40000, currency="JPY",
                       legs=[Leg(savings.id, debit=40000, capsule_id=capsule.id), Leg(savings.id, credit=40000)])
    db.commit()
    copy = scenarios.duplicate(db, 1, scenario.id, "転職")
    # The copy drops the car and adds a new event.
    db.delete(db.query(models.LifeEvent).filter_by(scenario_id=copy.id, name="車").one())
    db.commit()
    create(db, copy, "引越し", 80000, months_ahead(6), account_id=savings.id)
    return scenario, copy, savings, capsule, lone


def test_progress_comes_from_the_earmark_made_for_the_event(db):
    scenario, copy, savings, capsule, lone = _funded_goal(db)
    rows = {row["name"]: row for row in goal_earmark_service.events_with_progress(db, 1)}
    assert (rows["旅行"]["current_funded"], rows["旅行"]["gap"], rows["旅行"]["progress_percentage"]) == (40000, 60000, 40.0)
    assert rows["旅行"]["earmark"] == {"capsule_id": capsule.id, "capsule_name": "旅行"}


def test_changing_the_goal_previews_and_carries_earmarks_to_the_same_event(db):
    scenario, copy, savings, capsule, lone = _funded_goal(db)
    preview = goal_change_workflow.preview(db, 1, copy.id)
    assert preview["current_goal"]["name"] == "基本"
    assert {(row["capsule_name"], row["claim"], row["carry_to"]) for row in preview["capsules"]} == {("旅行", 40000, "旅行"), ("車", 0, None)}
    assert sorted(row["name"] for row in preview["create"]) == ["引越し", "旅行"]
    goal_change_workflow.apply(db, 1, copy.id, "carry")
    copied_trip = db.query(models.LifeEvent).filter_by(scenario_id=copy.id, name="旅行").one()
    db.expire_all()
    assert db.get(models.Capsule, capsule.id).goal_event_id == copied_trip.id
    # The car has no counterpart: its earmark stays with the old story.
    assert db.get(models.Capsule, lone.id).goal_event_id is not None
    assert {row["name"]: row["current_funded"] for row in goal_earmark_service.events_with_progress(db, 1)}["旅行"] == 40000


def test_replacing_deletes_the_old_earmarks_releases_their_money_and_makes_new_ones(db):
    scenario, copy, savings, capsule, lone = _funded_goal(db)
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 30000})
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    goal_budget_workflow.apply(db, 1, PERIOD, PERIOD, preview["fingerprint"])
    assert db.query(models.MonthlyPlanLine).filter_by(client_id=1, source_kind="goal", is_active=True).count() == 3
    goal_change_workflow.apply(db, 1, copy.id, "replace")
    db.expire_all()
    old_events = [row.id for row in db.query(models.LifeEvent).filter_by(scenario_id=scenario.id)]
    # (SQLite may hand the deleted ids to the new earmarks, so check by event.)
    assert db.query(models.Capsule).filter(models.Capsule.goal_event_id.in_(old_events)).count() == 0
    assert db.query(models.JournalEntry).filter(models.JournalEntry.capsule_id.isnot(None)).count() == 0
    assert db.query(models.MonthlyPlanLine).filter_by(client_id=1, source_kind="goal", is_active=True).count() == 0
    made = {row.name for row in db.query(models.Capsule).filter(models.Capsule.goal_event_id.isnot(None))}
    assert made == {"旅行", "引越し"}
    assert db.get(models.LifeScenario, copy.id).is_goal


def test_keeping_leaves_the_earmarks_with_the_old_story(db):
    scenario, copy, savings, capsule, lone = _funded_goal(db)
    goal_change_workflow.apply(db, 1, copy.id, "keep")
    db.expire_all()
    assert db.get(models.Capsule, capsule.id).goal_event_id == db.query(models.LifeEvent).filter_by(scenario_id=scenario.id, name="旅行").one().id
    assert capsule_service.capsule_to_dict(db, db.get(models.Capsule, capsule.id))["is_goal"] is False


def test_backup_upgrade_links_each_earmark_to_its_first_event_and_drops_subjects():
    data = migrate_goal_v2({
        "accounts": [{"id": 1, "account_type": "asset"}, {"id": 2, "account_type": "expense"}],
        "life_events": [{"id": 5, "account_id": 1}, {"id": 6, "account_id": 2}, {"id": 7, "account_id": None}],
        "capsules": [{"id": 8}, {"id": 9}],
        "goal_event_earmarks": [{"id": 2, "life_event_id": 6, "capsule_id": 8, "share_bp": 10000},
                                {"id": 1, "life_event_id": 5, "capsule_id": 8, "share_bp": 5000},
                                {"id": 3, "life_event_id": 7, "capsule_id": 9, "share_bp": 0}],
    })
    assert [(row["id"], row["goal_event_id"]) for row in data["capsules"]] == [(8, 5), (9, None)]
    assert [row["account_id"] for row in data["life_events"]] == [1, None, None]
    assert "goal_event_earmarks" not in data


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261019_0079_goal_v2.py"
    spec = importlib.util.spec_from_file_location("wp18_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_links_earmarks_to_events_and_keeps_only_asset_accounts():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_type VARCHAR)",
            "CREATE TABLE life_events (id INTEGER PRIMARY KEY, client_id INTEGER, direction VARCHAR NOT NULL, account_id INTEGER,"
            " CONSTRAINT ck_life_events_direction CHECK (direction IN ('expense', 'income')))",
            "CREATE TABLE scenario_contribution_plans (id INTEGER PRIMARY KEY, monthly_amount_minor BIGINT NOT NULL,"
            " CONSTRAINT ck_scenario_contribution_plans_amount CHECK (monthly_amount_minor >= 0))",
            "CREATE TABLE capsules (id INTEGER PRIMARY KEY, client_id INTEGER)",
            "CREATE TABLE goal_event_earmarks (id INTEGER PRIMARY KEY, client_id INTEGER, life_event_id INTEGER, capsule_id INTEGER, share_bp INTEGER)",
            "INSERT INTO accounts VALUES (1, 'asset'), (2, 'expense')",
            "INSERT INTO life_events VALUES (5, 1, 'expense', 1), (6, 1, 'expense', 2)",
            "INSERT INTO capsules VALUES (8, 1), (9, 1)",
            "INSERT INTO goal_event_earmarks VALUES (1, 1, 5, 8, 10000), (2, 1, 6, 8, 10000)",
        ):
            connection.exec_driver_sql(statement)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        assert connection.exec_driver_sql("SELECT id, goal_event_id FROM capsules ORDER BY id").all() == [(8, 5), (9, None)]
        assert connection.exec_driver_sql("SELECT id, account_id FROM life_events ORDER BY id").all() == [(5, 1), (6, None)]
        connection.exec_driver_sql("INSERT INTO life_events (id, client_id, direction) VALUES (7, 1, 'borrowing')")
        connection.exec_driver_sql("INSERT INTO scenario_contribution_plans VALUES (1, -500)")
        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()
        assert connection.exec_driver_sql("SELECT life_event_id, capsule_id FROM goal_event_earmarks").all() == [(5, 8)]
        assert connection.exec_driver_sql("SELECT count(*) FROM life_events WHERE direction = 'borrowing'").scalar() == 0
        assert connection.exec_driver_sql("SELECT monthly_amount_minor FROM scenario_contribution_plans").scalar() == 0
    engine.dispose()
