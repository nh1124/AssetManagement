"""WP23: 積立設定 records are 積立, 口座振替 or ライフイベントへの取り崩し, once or on a schedule; they add up."""
from datetime import date
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import models, schemas
from app.domain.transfer import migrate_plan_records
from app.services import contribution_plan_service as plans
from app.services import goal_plan_service, goal_service, life_scenario_service as scenarios
from app.workflows import goal_budget_workflow
from scenario_fixtures import account, db  # noqa: F401

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")


def months_ahead(months: int) -> date:
    index = TODAY.year * 12 + TODAY.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def month(when: date) -> str:
    return when.strftime("%Y-%m")


def goal(db, name="ゴール", is_goal=True, horizon_years=3):
    scenario = models.LifeScenario(client_id=1, name=name, is_goal=is_goal, annual_return=0, inflation=0, horizon_years=horizon_years)
    db.add(scenario)
    if db.query(models.SimulationConfig).filter_by(client_id=1).first() is None:
        db.add(models.SimulationConfig(client_id=1, volatility=0, tax_rate=0))
    db.commit()
    return scenario


def event(db, scenario, name, amount, when):
    return goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(
        scenario_id=scenario.id, name=name, target_amount=amount, target_date=when))


def balances(result) -> dict[int, list[float]]:
    return {row["account_id"]: row["p50"] for row in result["accounts"]}


def test_a_transfer_moves_money_between_accounts_and_skips_or_takes_what_is_there(db):
    bank, securities = account(db, "銀行", balance=100_000), account(db, "証券")
    for shortage, moved in (("skip", 90_000), ("partial", 100_000)):
        scenario = goal(db, shortage, is_goal=False)
        # 30,000 a month: the bank holds three months' worth, then a little.
        plans.create_plan(db, 1, scenario.id, {"kind": "transfer", "account_id": bank.id, "to_account_id": securities.id,
                                                "start_period": PERIOD, "amount": 30_000, "on_shortage": shortage})
        result = scenarios.project(db, 1, scenario)
        assert balances(result)[bank.id][:3] == [100_000, 100_000 - moved, 100_000 - moved]
        assert balances(result)[securities.id][:3] == [0, moved, moved]
        # Moving money between accounts leaves net worth alone; nothing comes in from elsewhere.
        assert {row["p50"] for row in result["projection"]} == {100_000}


def test_instalments_pay_the_event_from_its_month_and_the_rest_comes_from_net_worth(db):
    scenario = goal(db)
    savings = account(db, "貯蓄", balance=55_000)
    later = date(TODAY.year + 1, 1, 1)
    living = event(db, scenario, "老後生活", 120_000, later)
    plans.create_plan(db, 1, scenario.id, {"kind": "withdrawal", "account_id": savings.id, "start_period": month(later), "amount": 10_000,
                                            "interval_months": 1, "repeat_count": 12, "life_event_id": living.id})
    result = scenarios.project(db, 1, scenario)
    # The account gives what it holds (partial by default); the other 65,000 comes from the rest of net worth.
    assert balances(result)[savings.id][:3] == [55_000, 0, 0]
    assert [row["p50"] for row in result["projection"][:3]] == [55_000, 55_000 - 120_000, 55_000 - 120_000]
    assert {row["name"]: row["funded_probability"] for row in result["events"]}["老後生活"] == 0.0
    # The chart counts the instalments when they are due.
    assert [row["cumulative_target"] for row in result["projection"][:2]] == [0, 120_000]
    skipped = goal(db, "skip", is_goal=False)
    copy = event(db, skipped, "老後生活", 120_000, later)
    plans.create_plan(db, 1, skipped.id, {"kind": "withdrawal", "account_id": savings.id, "start_period": month(later), "amount": 10_000,
                                           "interval_months": 1, "repeat_count": 12, "life_event_id": copy.id, "on_shortage": "skip"})
    # Whole instalments only: five of them.
    assert balances(scenarios.project(db, 1, skipped))[savings.id][1] == 5_000


def test_the_plan_writes_transfers_with_their_source_and_draws_each_instalment_down(db):
    scenario = goal(db)
    bank, savings = account(db, "銀行", balance=500_000), account(db, "貯蓄")
    plans.create_plan(db, 1, scenario.id, {"kind": "transfer", "account_id": bank.id, "to_account_id": savings.id, "start_period": PERIOD, "amount": 20_000})
    # A yearly 積立 lands in its month only.
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": month(months_ahead(1)), "amount": 100_000, "interval_months": 12})
    trip = event(db, scenario, "旅行", 60_000, months_ahead(3))
    plans.create_plan(db, 1, scenario.id, {"kind": "withdrawal", "account_id": savings.id, "start_period": month(months_ahead(3)), "amount": 20_000,
                                            "interval_months": 1, "repeat_count": 3, "life_event_id": trip.id})
    end = month(months_ahead(4))
    preview = goal_budget_workflow.preview(db, 1, PERIOD, end)
    rows = {(row["period"], row["kind"], row["source_account_id"]): row["new"] for row in preview["changes"]}
    assert {key: value for key, value in rows.items() if key[1] == "transfer"} == {
        (month(months_ahead(offset)), "transfer", bank.id): 20_000 for offset in range(5)}
    assert {key[0]: value for key, value in rows.items() if key[1] == "account"} == {month(months_ahead(1)): 100_000}
    # The earmark holds what the three instalments take, set aside until the first one.
    assert [rows.get((month(months_ahead(offset)), "capsule", None)) for offset in range(5)] == [20_000, 20_000, 20_000, None, None]
    assert [rows.get((month(months_ahead(offset)), "drawdown", None)) for offset in range(5)] == [None, None, None, 20_000, 20_000]
    goal_budget_workflow.apply(db, 1, PERIOD, end, preview["fingerprint"])
    line = db.query(models.MonthlyPlanLine).filter_by(client_id=1, source_kind="goal", target_period=PERIOD, source_account_id=bank.id).one()
    assert (line.line_type, line.target_type, line.account_id, line.name, line.amount_minor) == ("allocation", "account", savings.id, "ゴールの振替", 20_000)
    assert not any(row["changed"] for row in goal_budget_workflow.preview(db, 1, PERIOD, end)["changes"])
    # The check compares what the 積立設定 brings into each account: the transfer; the earmark sits inside it.
    check = goal_plan_service.plan_check(db, 1, PERIOD)
    assert [(row["name"], row["contribution"], row["planned"]) for row in check["accounts"]] == [("貯蓄", 20_000, 20_000)]
    assert goal_plan_service.reflection_notifications(db, 1, month(months_ahead(5))) != []


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261021_0083_plan_record_kinds.py"
    spec = importlib.util.spec_from_file_location("wp23_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_gives_records_kinds_and_schedules_and_turns_monthly_withdrawals_into_events():
    now = TODAY.year * 12 + TODAY.month - 1
    times = max(1, now + 120 - (2030 * 12) + 1)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name VARCHAR)",
            "CREATE TABLE life_scenarios (id INTEGER PRIMARY KEY, client_id INTEGER, horizon_years INTEGER)",
            "CREATE TABLE life_events (id INTEGER PRIMARY KEY, client_id INTEGER, scenario_id INTEGER, lineage VARCHAR, name VARCHAR, target_date DATE,"
            " target_amount_minor BIGINT, priority INTEGER, note VARCHAR, condition_mode VARCHAR, direction VARCHAR, created_at DATETIME)",
            "CREATE TABLE scenario_contribution_plans (id INTEGER PRIMARY KEY, scenario_id INTEGER, account_id INTEGER, start_period VARCHAR(7),"
            " monthly_amount_minor BIGINT NOT NULL DEFAULT 0, annual_return FLOAT, note VARCHAR, life_event_id INTEGER, created_at DATETIME)",
            "CREATE UNIQUE INDEX uq_scenario_contribution_plans_month ON scenario_contribution_plans (scenario_id, account_id, start_period)"
            " WHERE life_event_id IS NULL",
            "CREATE UNIQUE INDEX uq_scenario_contribution_plans_event ON scenario_contribution_plans (scenario_id, account_id, start_period, life_event_id)"
            " WHERE life_event_id IS NOT NULL",
            "INSERT INTO accounts VALUES (3, '貯蓄')", "INSERT INTO life_scenarios VALUES (1, 1, 10)",
            "INSERT INTO life_events (id, client_id, scenario_id, name, direction) VALUES (5, 1, 1, '旅行', 'expense')",
            "INSERT INTO scenario_contribution_plans (id, scenario_id, account_id, start_period, monthly_amount_minor, annual_return, note, life_event_id)"
            " VALUES (1, 1, 3, '2026-10', 30000, 1.0, NULL, NULL), (2, 1, 3, '2028-04', 50000, NULL, NULL, NULL),"
            " (3, 1, 3, '2030-01', -10000, 2.0, '老後', NULL), (4, 1, 3, '2027-08', -400000, NULL, NULL, 5)",
        ):
            connection.exec_driver_sql(statement)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        rows = connection.exec_driver_sql(
            "SELECT id, kind, start_period, amount_minor, interval_months, repeat_count, end_period, on_shortage, annual_return, life_event_id"
            " FROM scenario_contribution_plans ORDER BY id").all()
        made = connection.exec_driver_sql("SELECT id, name, target_amount_minor, direction, target_date FROM life_events WHERE id <> 5").one()
        assert (made.name, made.target_amount_minor, made.direction, str(made.target_date)[:10]) == ("老後", 10000 * times, "expense", "2030-01-01")
        assert rows == [
            (1, "contribution", "2026-10", 30000, 1, None, "2028-03", None, 1.0, None),
            (2, "contribution", "2028-04", 50000, 1, None, "2029-12", None, None, None),
            # The monthly withdrawal now pays an event of its own until the horizon; its yield stays on a ¥0 積立.
            (3, "withdrawal", "2030-01", 10000, 1, times, None, "partial", None, made.id),
            (4, "withdrawal", "2027-08", 400000, None, None, None, "partial", None, 5),
            (5, "contribution", "2030-01", 0, 1, None, None, None, 2.0, None)]
        assert "monthly_amount_minor" not in {column["name"] for column in sa.inspect(connection).get_columns("scenario_contribution_plans")}
        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()
        back = connection.exec_driver_sql(
            "SELECT start_period, monthly_amount_minor, annual_return, life_event_id FROM scenario_contribution_plans ORDER BY start_period, id").all()
        stop = f"{(2030 * 12 + times) // 12:04d}-{(2030 * 12 + times) % 12 + 1:02d}"
        assert back == sorted([("2026-10", 30000, 1.0, None), ("2027-08", -400000, None, 5), ("2028-04", 50000, None, None),
                               ("2030-01", -10000, 2.0, None), (stop, 0, None, None)])
        assert "kind" not in {column["name"] for column in sa.inspect(connection).get_columns("scenario_contribution_plans")}
    engine.dispose()


def test_older_backups_get_kinds_and_schedules_like_the_migration():
    payload = {
        "accounts": [{"id": 3, "name": "貯蓄", "account_type": "asset"}],
        "life_scenarios": [{"id": 1, "name": "基本", "horizon_years": 10}],
        "life_events": [{"id": 5, "scenario_id": 1, "name": "旅行", "direction": "expense", "target_date": "2027-08-01", "target_amount": 400000}],
        "scenario_contribution_plans": [
            {"id": 1, "scenario_id": 1, "account_id": 3, "start_period": "2026-10", "monthly_amount_minor": 30000, "annual_return": 1.0, "note": None},
            {"id": 2, "scenario_id": 1, "account_id": 3, "start_period": "2030-01", "monthly_amount_minor": -10000, "annual_return": None, "note": None},
            {"id": 3, "scenario_id": 1, "account_id": 3, "start_period": "2027-08", "monthly_amount_minor": -400000, "annual_return": None,
             "note": None, "life_event_id": 5}],
    }
    data = migrate_plan_records(payload, "JPY", date(2026, 10, 1))
    times = 2026 * 12 + 9 + 120 - 2030 * 12 + 1
    assert [(row["kind"], row["amount_minor"], row["interval_months"], row["repeat_count"], row["end_period"], row["on_shortage"], row["life_event_id"])
            for row in data["scenario_contribution_plans"]] == [
        ("contribution", 30000, 1, None, "2029-12", None, None), ("withdrawal", 10000, 1, times, None, "partial", 6),
        ("withdrawal", 400000, None, None, None, "partial", 5)]
    made = data["life_events"][-1]
    assert (made["id"], made["name"], made["target_amount"], made["target_date"], len(made["lineage"])) == (6, "取り崩し（貯蓄）", 10000 * times, "2030-01-01", 36)
    assert "monthly_amount_minor" in payload["scenario_contribution_plans"][0]  # the verified payload itself is left untouched
