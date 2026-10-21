"""§8-11: 期間ごとの前提 set a scenario's default yield and inflation for some months."""
from datetime import date
from types import SimpleNamespace

import pytest

from app import models
from app.domain.errors import Refused
from app.domain.transfer import validate_import_payload
from app.services import contribution_plan_service as plans
from app.services import life_scenario_service as scenarios
from app.services.data_transfer_service import export_client, import_client
from scenario_fixtures import account, db  # noqa: F401

TODAY = date.today()
NEXT_YEAR = f"{TODAY.year + 1}-01"


def scenario_of(db, name="試算"):
    scenario = models.LifeScenario(client_id=1, name=name, annual_return=0, inflation=0, horizon_years=3)
    db.add(scenario)
    if db.query(models.SimulationConfig).filter_by(client_id=1).first() is None:
        db.add(models.SimulationConfig(client_id=1, volatility=0, tax_rate=0))
    db.commit()
    return scenario


def row(start, end=None, annual_return=None, inflation=None, id=1):
    return SimpleNamespace(id=id, start_period=start, end_period=end, annual_return=annual_return, inflation=inflation)


def test_the_latest_starting_record_over_a_month_sets_each_field_and_the_scenario_default_fills_the_rest():
    rows = [row("2027-01", "2029-12", annual_return=3.0, inflation=1.0, id=1),
            row("2028-01", None, annual_return=6.0, id=2)]
    assert plans.assumption(rows, "2026-12", "annual_return", 5.0) == 5.0
    assert plans.assumption(rows, "2027-06", "annual_return", 5.0) == 3.0
    # From 2028 the later record sets the yield; it names no inflation, so the earlier record's stays.
    assert plans.assumption(rows, "2028-03", "annual_return", 5.0) == 6.0
    assert plans.assumption(rows, "2028-03", "inflation", 2.0) == 1.0
    # After the first record ends its inflation goes; the open record keeps its yield.
    assert plans.assumption(rows, "2030-01", "inflation", 2.0) == 2.0
    assert plans.assumption(rows, "2030-01", "annual_return", 5.0) == 6.0


def test_a_record_needs_a_rate_and_an_end_after_its_start(db):
    scenario = scenario_of(db)
    with pytest.raises(Refused, match="年利かインフレ"):
        plans.create_period(db, 1, scenario.id, {"start_period": NEXT_YEAR})
    with pytest.raises(Refused, match="終了月"):
        plans.create_period(db, 1, scenario.id, {"start_period": NEXT_YEAR, "end_period": f"{TODAY.year}-12", "inflation": 3})
    created = plans.create_period(db, 1, scenario.id, {"start_period": NEXT_YEAR, "inflation": 3, "note": " 物価高 "})
    assert plans.serialize_period(created) == {"id": created.id, "scenario_id": scenario.id, "start_period": NEXT_YEAR,
                                               "end_period": None, "annual_return": None, "inflation": 3.0, "note": "物価高"}
    with pytest.raises(Refused, match="年利かインフレ"):
        plans.update_period(db, 1, created.id, {"inflation": None})
    assert db.get(models.ScenarioAssumptionPeriod, created.id).inflation == 3.0
    # Another client's record is not found.
    other = models.LifeScenario(client_id=2, name="他", annual_return=0, inflation=0, horizon_years=3)
    db.add(other)
    db.commit()
    foreign = plans.create_period(db, 2, other.id, {"start_period": NEXT_YEAR, "annual_return": 1})
    with pytest.raises(Exception, match="見つかりません"):
        plans.delete_period(db, 1, foreign.id)


def test_the_simulation_uses_a_records_yield_for_accounts_without_their_own_and_its_inflation(db):
    securities = account(db, "証券", balance=1_000_000)
    scenario = scenario_of(db)
    plans.create_plan(db, 1, scenario.id, {"account_id": securities.id, "start_period": f"{TODAY.year}-{TODAY.month:02d}", "amount": 0})
    flat = scenarios.project(db, 1, scenario)
    assert [row["p50"] for row in flat["projection"]] == [1_000_000] * 4
    # From next year the default yield is 10% (volatility and tax are 0 here).
    plans.create_period(db, 1, scenario.id, {"start_period": NEXT_YEAR, "annual_return": 10})
    grown = scenarios.project(db, 1, scenario)
    assert [round(value) for value in grown["accounts"][0]["p50"]] == [1_000_000, 1_100_000, 1_210_000, 1_331_000]
    # A 10% inflation in the second year only: that year's real yield is 0.
    plans.create_period(db, 1, scenario.id, {"start_period": f"{TODAY.year + 2}-01", "end_period": f"{TODAY.year + 2}-12", "inflation": 10})
    deflated = scenarios.project(db, 1, scenario)
    assert [round(value) for value in deflated["accounts"][0]["p50"]] == [1_000_000, 1_100_000, 1_100_000, 1_210_000]
    # An account's own 積立設定 yield comes first.
    plans.create_plan(db, 1, scenario.id, {"account_id": securities.id, "start_period": NEXT_YEAR, "amount": 0, "annual_return": 0})
    assert [round(value) for value in scenarios.project(db, 1, scenario)["accounts"][0]["p50"]] == [1_000_000, 1_000_000, 900_000, 900_000]


def test_a_duplicate_copies_the_records_and_the_backup_carries_them(db):
    scenario = scenario_of(db)
    plans.create_period(db, 1, scenario.id, {"start_period": NEXT_YEAR, "end_period": f"{TODAY.year + 5}-12", "annual_return": 4, "inflation": 1.5})
    copy = scenarios.duplicate(db, 1, scenario.id, "写し")
    assert [(row["start_period"], row["annual_return"], row["inflation"]) for row in scenarios.describe(db, 1, copy)["assumption_periods"]] == [
        (NEXT_YEAR, 4.0, 1.5)]
    document = export_client(db, db.get(models.Client, 1))
    assert document["version"] == 31
    assert len(document["data"]["scenario_assumption_periods"]) == 2
    result = import_client(db, db.get(models.Client, 3), data=document["data"], version=document["version"], manifest=document["manifest"])
    assert result["status"] == "ok"
    restored = db.query(models.ScenarioAssumptionPeriod).join(models.LifeScenario).filter(models.LifeScenario.client_id == 3).all()
    assert sorted((row.start_period, row.annual_return, row.inflation) for row in restored) == [(NEXT_YEAR, 4.0, 1.5)] * 2


def test_the_backup_refuses_a_record_without_a_rate():
    payload = {"life_scenarios": [{"id": 1, "name": "基本", "horizon_years": 10}],
               "scenario_assumption_periods": [{"id": 1, "scenario_id": 1, "start_period": "2027-01"}]}
    codes = {issue["code"] for issue in validate_import_payload(payload, 31)["issues"]}
    assert "invalid_assumption_period" in codes
