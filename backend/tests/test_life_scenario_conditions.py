"""Scenario preconditions describe the same paths, before the resolved event."""
import json
from datetime import date

import numpy as np
import pytest
from sqlalchemy import event as sqlalchemy_event

from app import models
from app.services import life_event_conditions as evaluator, life_scenario_service as service
from app.services import strategy_service as strategy
from app.services.institution_service import positive_asset_balance
from test_life_scenarios import account, api, config, db, fork, node, request


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2030, 6, 15)


@pytest.fixture(autouse=True)
# Projection rows step a whole year from today, so a judgement in year Y is
# labelled with today's month and day (06-15 under this fixed date) in Y.
def calendar(monkeypatch):
    monkeypatch.setattr(strategy, "date", FixedDate)
    monkeypatch.setattr(evaluator, "date", FixedDate)


def at(db, when, **values):
    row = node(db, **values)
    row.target_date = when
    db.commit()
    return row


def condition(db, owner, metric="net_worth", comparator="gte", **values):
    row = models.LifeEventCondition(client_id=owner.client_id, life_event_id=owner.id,
                                    metric=metric, comparator=comparator, **values)
    db.add(row)
    db.commit()
    return row


def scenario(db, **values):
    saved = service.create(db, 1, "試算")
    return service.update(db, 1, saved.id, {"horizon_years": 8, "inflation": 0, **values})


def test_bands_are_byte_identical_to_pre_ls2_seed_42_case(db):
    account(db, rate=3.5, balance=1000000)
    config(db)
    result = strategy.simulate_net_worth_forward(db, 1, years=4, annual_return=7.5, inflation=1.5)
    # With only positive assets and no debts, the earning pool is the old held pool.
    assert positive_asset_balance(db, 1) == strategy.get_balance_sheet(db, client_id=1)["net_worth"] == 1000000
    # Captured from the original implementation before factoring the simulation.
    expected = ('[{"year":2030,"p10":1000000.0,"p50":1000000.0,"p90":1000000.0,"cumulative_income":0},'
                '{"year":2031,"p10":1332809.0,"p50":1640829.0,"p90":1948986.0,"cumulative_income":0},'
                '{"year":2032,"p10":1740900.0,"p50":2275570.0,"p90":2794484.0,"cumulative_income":0},'
                '{"year":2033,"p10":2253452.0,"p50":2934836.0,"p90":3821986.0,"cumulative_income":0},'
                '{"year":2034,"p10":2716417.0,"p50":3629429.0,"p90":4836262.0,"cumulative_income":0}]')
    assert json.dumps(result, separators=(",", ":")).encode() == expected.encode()


@pytest.mark.parametrize("include_income", [False, True])
def test_paths_match_bands_and_income_adjustment(db, include_income):
    account(db, rate=3.5, balance=1000000)
    config(db)
    at(db, date(2032, 2, 1), direction="income", amount=120000)
    bands, paths = strategy.simulate_net_worth_forward_with_paths(db, 1, years=4, include_event_income=include_income)
    assert paths.shape == (1200, 5)
    assert bands == strategy.simulate_net_worth_forward(db, 1, years=4, include_event_income=include_income)
    for index, row in enumerate(bands):
        assert [row[key] for key in ("p10", "p50", "p90")] == [round(float(value), 0) for value in np.percentile(paths[:, index], [10, 50, 90])]


def test_projection_runs_only_one_seeded_simulation(db, monkeypatch):
    owner = at(db, date(2034, 1, 1))
    condition(db, owner, threshold_minor=1000000)
    saved = scenario(db)
    original = np.random.default_rng
    seeds, draws = [], []

    class Generator:
        def __init__(self, seed):
            seeds.append(seed)
            self.rng = original(seed)

        def normal(self, *args):
            draws.append(args)
            return self.rng.normal(*args)

    monkeypatch.setattr(strategy.np.random, "default_rng", Generator)
    service.project(db, 1, saved)
    assert seeds == [strategy.PROJECTION_SEED]
    assert len(draws) == saved.horizon_years


def test_net_worth_probability_extremes_and_scenario_return(db):
    config(db)
    owner = at(db, date(2036, 1, 1))
    for amount in (1, 1000000000, 4000000):
        condition(db, owner, threshold_minor=amount)
    saved = scenario(db, annual_return=0)
    low = service.project(db, 1, saved)["conditions"][0]["conditions"]
    service.update(db, 1, saved.id, {"annual_return": 20})
    high = service.project(db, 1, saved)["conditions"][0]["conditions"]
    assert low[0]["probability"] > .99 and high[0]["probability"] > .99
    assert low[1]["probability"] < .01 and high[1]["probability"] < .01
    assert 0 < low[2]["probability"] < high[2]["probability"] < 1
    assert all(row["basis"] == "projected" for row in low + high)


@pytest.mark.parametrize("when", [date(2030, 8, 1), date(2031, 8, 1), date(2033, 8, 1)])
def test_down_payment_is_judged_before_own_year_expense(db, when):
    account(db, rate=0, balance=1000000)
    config(db, monthly_savings_minor=0, volatility=0)
    owner = at(db, when, amount=900000)
    condition(db, owner, threshold_minor=1000000)
    result = service.project(db, 1, scenario(db))
    judgement = result["conditions"][0]
    assert judgement["probability"] == 1
    assert judgement["conditions"][0]["actual"] == 1000000
    assert result["projection"][when.year - 2030]["p50"] == 100000
    assert judgement["judged_at"] == ("2030-06-15" if when.year <= 2031 else "2032-06-15")


def test_prior_expenses_and_income_adjust_the_same_paths(db):
    config(db, volatility=0, monthly_savings_minor=0)
    account(db, rate=0, balance=1000000)
    at(db, date(2031, 1, 1), amount=800000)
    at(db, date(2032, 1, 1), direction="income", amount=500000)
    owner = at(db, date(2033, 1, 1), amount=1000000)
    condition(db, owner, threshold_minor=700000, comparator="eq")
    result = service.project(db, 1, scenario(db))["conditions"][0]
    assert result["conditions"][0]["actual"] == 700000
    assert result["probability"] == 1


@pytest.mark.parametrize("age, threshold_date", [(18, date(2032, 2, 29)), (17, date(2032, 2, 29)), (18, date(2032, 2, 28))])
def test_calendar_conditions_use_resolved_date_after_link_offset(db, age, threshold_date):
    root = at(db, date(2031, 11, 30))
    owner = at(db, date(2030, 1, 1))
    member = models.HouseholdMember(client_id=1, name="子", birth_date=date(2014, 2, 28))
    db.add_all([member, models.LifeEventLink(client_id=1, from_event_id=root.id, to_event_id=owner.id,
                                            kind="after", offset_months=3)])
    db.commit()
    condition(db, owner, "member_age", "eq", reference_id=member.id, threshold_number=age)
    condition(db, owner, "date_reached", "eq", threshold_date=threshold_date)
    result = service.project(db, 1, scenario(db))["conditions"][0]
    assert result["judged_at"] == "2031-06-15"
    assert [row["actual"] for row in result["conditions"]] == [18, date(2032, 2, 29)]
    expected = [age == 18, threshold_date == date(2032, 2, 29)]
    assert result["probability"] == float(all(expected))
    for row, satisfied in zip(result["conditions"], expected):
        assert row["basis"] == "projected" and row["satisfied"] is satisfied and row["probability"] == float(satisfied)


@pytest.mark.parametrize("metric", ["free_cash", "account_balance", "capsule_claim", "goal_progress"])
def test_current_metrics_use_exactly_the_existing_today_evaluator(db, metric):
    owner = at(db, date(2034, 1, 1), amount=1000)
    cash = account(db, name="cash", balance=500)
    capsule = models.Capsule(client_id=1, name="学費", target_amount_minor=1000, life_event_id=owner.id)
    db.add(capsule)
    db.flush()
    db.query(models.JournalEntry).filter_by(account_id=cash.id).one().capsule_id = capsule.id
    db.commit()
    references = {"account_balance": cash.id, "capsule_claim": capsule.id, "goal_progress": owner.id}
    values = {"threshold_number": 10} if metric == "goal_progress" else {"threshold_minor": 100}
    condition(db, owner, metric, reference_id=references.get(metric), **values)
    saved = scenario(db)
    expected = evaluator.evaluate(db, 1, owner.id)["conditions"][0]
    commits = []
    sqlalchemy_event.listen(db, "after_commit", lambda _: commits.append(True))
    result = service.project(db, 1, saved)["conditions"][0]["conditions"][0]
    assert result["basis"] == "current"
    assert {key: result[key] for key in expected} == expected
    assert result["probability"] == float(expected["satisfied"])
    assert commits == [] and not db.dirty and not db.new and not db.deleted


@pytest.mark.parametrize("mode", ["all", "any"])
def test_conditions_combine_on_identical_paths_instead_of_multiplying_marginals(db, mode):
    account(db, rate=3.5, balance=1000000)
    config(db)
    owner = at(db, date(2034, 1, 1), condition_mode=mode)
    condition(db, owner, "net_worth", "gte", threshold_minor=2500000)
    condition(db, owner, "net_worth", "lte", threshold_minor=3500000)
    saved = scenario(db)
    result = service.project(db, 1, saved)["conditions"][0]
    _, paths = strategy.simulate_net_worth_forward_with_paths(db, 1, years=8, annual_return=5, inflation=0, include_event_income=False)
    lower, upper = paths[:, 3] >= 2500000, paths[:, 3] <= 3500000
    expected = float(np.mean(lower & upper if mode == "all" else lower | upper))
    assert result["probability"] == expected
    first, second = [row["probability"] for row in result["conditions"]]
    assert 0 < first < 1 and 0 < second < 1
    product = first * second if mode == "all" else 1 - (1 - first) * (1 - second)
    assert result["probability"] != pytest.approx(product)


@pytest.mark.parametrize("mode, threshold, expected", [
    ("all", 1, None), ("all", 1000000000, 0),
    ("any", 1, 1), ("any", 1000000000, None),
    ("all", 3000000, None), ("any", 3000000, None),
])
def test_unknown_current_value_obeys_three_valued_rules_per_path(db, mode, threshold, expected):
    owner = at(db, date(2036, 1, 1), condition_mode=mode)
    condition(db, owner, "account_balance", reference_id=99999, threshold_minor=1)
    condition(db, owner, threshold_minor=threshold)
    result = service.project(db, 1, scenario(db))["conditions"][0]
    assert result["conditions"][0]["probability"] is None
    assert result["conditions"][0]["satisfied"] is None
    assert result["probability"] == expected


def test_net_worth_equality_broadcasts_the_p50_judgement(db):
    config(db)
    owner = at(db, date(2034, 1, 1))
    saved = scenario(db)
    median = service.project(db, 1, saved)["projection"][3]["p50"]
    row = condition(db, owner, comparator="eq", threshold_minor=int(median))
    result = service.project(db, 1, saved)["conditions"][0]
    assert result["probability"] == 1 and result["conditions"][0]["satisfied"] is True
    row.threshold_minor += 1
    db.commit()
    result = service.project(db, 1, saved)["conditions"][0]
    assert result["probability"] == 0 and result["conditions"][0]["satisfied"] is False


def test_branch_choices_judge_shared_event_at_different_dates(db):
    root, children, edges = fork(db)
    root.target_date = date(2031, 1, 1)
    shared = at(db, date(2031, 1, 1))
    db.add_all([models.LifeEventLink(client_id=1, from_event_id=child.id, to_event_id=shared.id,
                                   kind="after", offset_months=offset) for child, offset in zip(children, [12, 36])])
    db.commit()
    condition(db, shared, "date_reached", threshold_date=date(2033, 1, 1))
    first = scenario(db)
    second = service.duplicate(db, 1, first.id, "別案")
    service.replace_choices(db, 1, first.id, [edges[0].id])
    service.replace_choices(db, 1, second.id, [edges[1].id])
    earlier, later = [service.project(db, 1, item)["conditions"][0] for item in (first, second)]
    assert earlier["event_id"] == later["event_id"] == shared.id
    assert (earlier["judged_at"], earlier["probability"]) == ("2031-06-15", 0)
    assert (later["judged_at"], later["probability"]) == ("2033-06-15", 1)


def test_only_resolved_events_with_conditions_are_reported_and_serialized(db, api):
    root, children, edges = fork(db)
    root.target_date = date(2031, 1, 1)
    foreign = at(db, date(2032, 1, 1), client_id=2)
    for owner in [*children, foreign]:
        condition(db, owner, "date_reached", threshold_date=date(2032, 1, 1))
    saved = scenario(db)
    service.replace_choices(db, 1, saved.id, [edges[0].id])
    response = request(api, "GET", f"/life-scenarios/compare?ids={saved.id}")
    assert response.status_code == 200
    results = response.json()["scenarios"][0]["conditions"]
    assert len(results) == 1 and results[0]["event_id"] == children[0].id
    assert results[0]["event_name"] == children[0].name
    assert results[0]["conditions"][0]["threshold_date"] == "2032-01-01"


def test_event_outside_projection_horizon_has_unknown_net_worth(db):
    owner = at(db, date(2035, 1, 1))
    condition(db, owner, threshold_minor=1)
    result = service.project(db, 1, scenario(db, horizon_years=2))["conditions"][0]
    assert result["judged_at"] == "2034-06-15"
    assert result["probability"] is None
    assert result["conditions"][0]["actual"] is None
