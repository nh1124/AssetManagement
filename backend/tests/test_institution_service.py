"""Shelters affect estimates and access, never the recorded holdings."""
from datetime import date

import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from scenario_fixtures import goal_scenario_id

from app import models, schemas
from app.database import Base
from app.domain.errors import Invalid
from app.domain.transfer import EXPORT_VERSION
from app.routers.accounts import AccountCreate, AccountResponse, AccountUpdate, _serialize_account
from app.services.analysis_service import calculate_logical_balance, get_summary
from app.services.data_transfer_service import export_client, import_client
from app.services.institution_service import (
    blended_after_tax_return, locked_accounts, locked_until_age_minor, shelter_breakdown,
)
from app.services.ledger_service import create_account, create_transaction, update_account
from app.services.ledger_valuation import calculate_account_balances
from app.services.strategy_service import (
    PROJECTION_SEED, calculate_projection, generate_roadmap, get_goal_simulation_context, get_life_events_with_progress,
    simulate_net_worth_forward,
)
from app.workflows.simulation_workflow import monte_carlo_for_goal


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add_all([models.Client(id=1, name="本人", general_settings={"currency": "JPY"}),
                         models.Client(id=2, name="別人", general_settings={"currency": "JPY"})])
        session.commit()
        yield session
    engine.dispose()


def account(db, name="cash", institution="none", rate=None, age=None, client_id=1, parent_id=None):
    return create_account(db, client_id, {"name": name, "account_type": "asset", "institution": institution,
                                         "expected_return": rate, "withdrawable_from_age": age, "parent_id": parent_id})


def fund(db, account, minor=1000, currency="JPY"):
    income = db.query(models.Account).filter_by(client_id=account.client_id, name="給与").first()
    if income is None:
        income = create_account(db, account.client_id, {"name": "給与", "account_type": "income"})
    transaction = create_transaction(db, client_id=account.client_id, date=date(2020, 1, 1),
                              description="開始残高", amount_minor=minor, currency=currency,
                              from_account_id=income.id, to_account_id=account.id)
    db.commit()
    return transaction


def member(db, born=date(1970, 10, 15), relation="本人", name="本人", client_id=1):
    row = models.HouseholdMember(client_id=client_id, name=name, relation=relation, birth_date=born)
    db.add(row)
    db.commit()
    return row


def goal(db):
    row = models.LifeEvent(scenario_id=goal_scenario_id(db, 1), client_id=1, name="目標", target_date=date.today().replace(year=date.today().year + 2),
                           target_amount_minor=1000)
    config = models.SimulationConfig(client_id=1, annual_return=10, tax_rate=25, volatility=0,
                                     inflation_rate=0, monthly_savings_minor=0, is_nisa=True)
    db.add_all([row, config])
    db.commit()
    return row


@pytest.mark.parametrize("shelter,taxed", [
    ("none", True), ("general", True), ("tokutei_withholding", True), ("tokutei_self", True),
    ("nisa_tsumitate", False), ("nisa_growth", False), ("ideco", False), ("dc_corporate", False),
])
def test_each_shelter_uses_configured_tax_without_posting(db, shelter, taxed):
    row = account(db, institution=shelter, rate=10)
    fund(db, row)
    before = [(leg.id, leg.debit_minor, leg.credit_minor) for leg in db.query(models.JournalEntry)]
    assert blended_after_tax_return(db, 1, gross_annual_return=12, tax_rate=25) == (7.5 if taxed else 10)
    assert shelter_breakdown(db, 1) == [{"institution": shelter, "currency": "JPY", "balance": 1000, "taxed": taxed}]
    assert before == [(leg.id, leg.debit_minor, leg.credit_minor) for leg in db.query(models.JournalEntry)]


def test_mix_uses_account_rate_or_projection_rate_and_never_rolls_up_twice(db):
    parent = account(db, name="資産", rate=99)
    taxable = account(db, rate=10, parent_id=parent.id)
    sheltered = account(db, name="NISA", institution="nisa_growth", parent_id=parent.id)
    assert sheltered.expected_return is None
    fund(db, taxable, 1000)
    fund(db, sheltered, 3000)
    fund(db, account(db, name="別人", rate=100, client_id=2), 9000)
    assert blended_after_tax_return(db, 1, gross_annual_return=8, tax_rate=20) == 8
    assert blended_after_tax_return(db, 1, gross_annual_return=12, tax_rate=20) == 11
    # The blend weights the earning pool, which must sit inside the net worth the
    # projection starts from -- and the balance sheet counts active accounts only.
    # Once the taxable account is inactive, only the sheltered 3000 earns: 12.
    taxable.is_active = False
    db.commit()
    assert blended_after_tax_return(db, 1, gross_annual_return=12, tax_rate=20) == 12


def test_explicit_zero_rate_is_not_missing(db):
    row = account(db, rate=0)
    fund(db, row)
    assert blended_after_tax_return(db, 1, gross_annual_return=10, tax_rate=20) == 0


def test_no_holdings_uses_taxable_projection_assumption(db):
    assert blended_after_tax_return(db, 1, gross_annual_return=10, tax_rate=25) == 7.5


def test_foreign_money_remains_separate_and_does_not_weight_client_rate(db):
    row = account(db, rate=10)
    fund(db, row, 1000)
    fund(db, row, 12345, "USD")
    foreign = account(db, name="外貨NISA", institution="nisa_growth", rate=90)
    fund(db, foreign, 9999999, "EUR")
    assert blended_after_tax_return(db, 1, gross_annual_return=12, tax_rate=25) == 7.5
    assert shelter_breakdown(db, 1) == [
        {"institution": "nisa_growth", "currency": "EUR", "balance": 99999.99, "taxed": False},
        {"institution": "none", "currency": "JPY", "balance": 1000, "taxed": True},
        {"institution": "none", "currency": "USD", "balance": 123.45, "taxed": True},
    ]


@pytest.mark.parametrize("as_of,locked", [(date(2030, 10, 14), True), (date(2030, 10, 15), False), (date(2030, 10, 16), False)])
def test_locked_before_age_free_on_and_after_birthday(db, as_of, locked):
    row = account(db, institution="ideco", age=60)
    fund(db, row)
    member(db)
    assert locked_until_age_minor(locked_accounts(db, 1, as_of=as_of)) == ({"JPY": 1000} if locked else {})
    assert calculate_logical_balance(db, 1, as_of=as_of) == (0 if locked else 1000)


def test_missing_member_locks_nothing_even_with_other_clients_member(db):
    row = account(db, institution="dc_corporate", age=60)
    fund(db, row)
    member(db, client_id=2)
    assert locked_accounts(db, 1) == []
    assert calculate_logical_balance(db, 1) == 1000


def test_no_age_never_locks_and_no_default_age_is_invented(db):
    row = account(db, institution="ideco")
    fund(db, row)
    member(db, born=date(2000, 1, 1))
    assert row.withdrawable_from_age is None
    assert locked_accounts(db, 1) == []
    assert calculate_logical_balance(db, 1) == 1000


def test_relation_self_wins_over_older_person_and_name_does_not_choose_self(db):
    row = account(db, age=60)
    fund(db, row)
    member(db, born=date(1950, 1, 1), relation="母", name="本人")
    member(db, born=date(2000, 1, 1), relation="本人", name="太郎")
    assert locked_until_age_minor(locked_accounts(db, 1, as_of=date(2030, 1, 1))) == {"JPY": 1000}


def test_fallback_uses_earliest_birth_date(db):
    row = account(db, age=60)
    fund(db, row)
    member(db, born=date(2000, 1, 1), relation="子", name="子")
    member(db, born=date(1950, 1, 1), relation="母", name="母")
    assert locked_accounts(db, 1, as_of=date(2030, 1, 1)) == []


def test_leap_day_unlock_matches_v2_march_first(db):
    row = account(db, age=61)
    fund(db, row)
    member(db, born=date(1968, 2, 29))
    assert locked_accounts(db, 1, as_of=date(2029, 2, 28))[0]["available_on"] == "2029-03-01"
    assert locked_accounts(db, 1, as_of=date(2029, 3, 1)) == []


def test_all_locked_assets_and_currencies_reported_without_cross_currency_sum(db):
    row = account(db, institution="ideco", age=65)
    other = account(db, name="年金", institution="dc_corporate", age=60)
    fund(db, row, 1000)
    fund(db, row, 12345, "USD")
    fund(db, other, 500)
    member(db, born=date(2000, 1, 1))
    summary = get_summary(db, 1)
    assert summary["locked_until_age_minor"] == {"JPY": 1500, "USD": 12345}
    assert {row["available_on"] for row in summary["locked_accounts"]} == {"2060-01-01", "2065-01-01"}
    # Everything locked is reported, but only what the liquid total counted is
    # subtracted from free cash. The liquid figure is a named set of accounts and
    # 年金 is not in it, so taking its 500 off as well would remove money this sum
    # never added -- the free-cash figure would understate by the balance of every
    # retirement account, which is exactly the kind of account this locks.
    unlocked = calculate_logical_balance(db, 1, as_of=date(2070, 1, 1))
    assert calculate_logical_balance(db, 1) == unlocked - 1000
    schemas.AnalysisSummary.model_validate(summary)


def test_goal_context_deterministic_monte_carlo_and_forward_share_blend_once(db):
    row = account(db, rate=10)
    fund(db, row)
    owner = goal(db)
    capsule = models.Capsule(client_id=1, name="目標", life_event_id=owner.id)
    db.add(capsule)
    db.flush()
    db.query(models.JournalEntry).filter_by(account_id=row.id).one().capsule_id = capsule.id
    db.commit()
    context = get_goal_simulation_context(db, 1, owner, annual_return=12, monthly_savings=0, inflation=0)
    assert context["annual_return"] == 12
    assert context["effective_return"] == 7.5
    assert context["tax_rate"] == 25
    progress = get_life_events_with_progress(db, 1, annual_return=12, monthly_savings=0, inflation=0)[0]
    assert progress["blended_after_tax_return"] == 7.5
    assert progress["projected_amount"] == round(calculate_projection(1000, 0, context["years_remaining"], 7.5), 2)
    mc = monte_carlo_for_goal(db, 1, owner.id, n_simulations=100, annual_return=12, inflation=0,
                              monthly_savings=0, contribution_schedule=None, allocation_mode="direct")
    assert mc["percentiles"]["p50"] == round(progress["projected_amount"])
    assert simulate_net_worth_forward(db, 1, years=1, annual_return=12, inflation=0, monthly_savings=0)[1]["p50"] == 1075


@pytest.mark.parametrize("tax_rate", [None, 25])
def test_forward_zero_rate_holdings_use_simulation_rate_only_for_new_savings(db, tax_rate):
    fund(db, account(db, rate=0), 1000)
    if tax_rate is not None:
        goal(db)
    low = simulate_net_worth_forward(db, 1, years=5, annual_return=0, monthly_savings=100)
    high = simulate_net_worth_forward(db, 1, years=5, annual_return=12, monthly_savings=100)
    assert high[-1]["p50"] > low[-1]["p50"]
    assert high[0] == low[0]
    held_low = simulate_net_worth_forward(db, 1, years=5, annual_return=0, monthly_savings=0)
    held_high = simulate_net_worth_forward(db, 1, years=5, annual_return=12, monthly_savings=0)
    assert held_high == held_low
    assert db.query(models.Account).filter_by(account_type="asset").one().expected_return == 0


def test_forward_zero_rate_holdings_only_lose_inflation_without_market_noise(db):
    fund(db, account(db, rate=0), 1000)
    goal(db)
    rows = simulate_net_worth_forward(db, 1, years=3, annual_return=12, inflation=2, monthly_savings=0)
    assert [row["p50"] for row in rows] == [round(1000 * .98 ** year) for year in range(4)]
    assert all(row["p10"] == row["p50"] == row["p90"] for row in rows)


def test_forward_pools_share_one_market_shock_and_repeat_bands(db):
    fund(db, account(db, rate=0), 1000)
    # No config: contributions use the default 20% tax and 15% volatility.
    args = dict(years=1, annual_return=10, inflation=2, monthly_savings=100)
    first = simulate_net_worth_forward(db, 1, **args)
    assert first == simulate_net_worth_forward(db, 1, **args)
    shocks = np.percentile(np.random.default_rng(PROJECTION_SEED).normal(0, .15, 1200), [10, 50, 90])
    # With one shared shock, both principals have the same random multiplier.
    for band, shock in zip(("p10", "p50", "p90"), shocks):
        assert first[1][band] == round(1000 * .98 + 1200 * 1.06 + 2200 * shock)
    assert first[0] == dict(year=date.today().year, p10=1000, p50=1000, p90=1000, cumulative_income=0)
    without_income = simulate_net_worth_forward(db, 1, **args, include_event_income=False)
    assert [{key: value for key, value in row.items() if key != "cumulative_income"} for row in first] == without_income


@pytest.mark.parametrize("monthly_savings", [0, 100])
def test_goal_consumers_keep_held_rate_and_invest_future_savings_at_requested_rate(db, monthly_savings):
    from app.services import milestone_service, simulation_scenario_service

    row = account(db, rate=0)
    fund(db, row)
    owner = goal(db)
    capsule = models.Capsule(client_id=1, name="目標", life_event_id=owner.id)
    db.add(capsule)
    db.flush()
    db.query(models.JournalEntry).filter_by(account_id=row.id).one().capsule_id = capsule.id
    db.commit()
    scenarios = [simulation_scenario_service.create_scenario(
        db, 1, schemas.SimulationScenarioCreate(life_event_id=owner.id, name=f"rate {rate}",
                                               annual_return=rate, inflation=0, monthly_savings=monthly_savings,
                                               allocation_mode="direct"),
    ) for rate in (0, 12)]
    compared_rows = simulation_scenario_service.compare_scenarios(
        db, 1, schemas.SimulationScenarioCompareRequest(life_event_id=owner.id, scenario_ids=[item.id for item in scenarios]),
    )
    results = []
    for rate, compared in zip((0, 12), compared_rows):
        inputs = dict(annual_return=rate, inflation=0, monthly_savings=monthly_savings, allocation_mode="direct")
        context = get_goal_simulation_context(db, 1, owner, **inputs)
        assert context["effective_return"] == 0
        assert context["contribution_annual_return"] == rate * .75
        progress = get_life_events_with_progress(db, 1, **inputs)[0]
        mc = monte_carlo_for_goal(db, 1, owner.id, n_simulations=100, contribution_schedule=None, **inputs)
        values = [progress["projected_amount"], progress["roadmap"][-1]["end_balance"], mc["percentiles"]["p50"],
                  compared["percentiles"]["p50"], compared["deterministic_yearly"][-1]["end_balance"]]
        for basis in ("deterministic", "p50", "annual_plan"):
            preview = milestone_service.preview_milestones_from_simulation(db, 1, owner.id, basis=basis, **inputs)
            values.append(preview["items"][0]["target_amount"])
        results.append(values)
    if monthly_savings:
        assert all(high > low for low, high in zip(*results))
    else:
        assert results[0] == results[1] == [1000] * 8


@pytest.mark.parametrize("interval,periods,contribution", [("monthly", 12, 100), ("quarterly", 4, 300), ("annual", 1, 1200)])
def test_roadmap_rates_apply_to_separate_pools_at_each_interval(interval, periods, contribution):
    rows = generate_roadmap(1000, 100, 1, annual_return=0, contribution_annual_return=12,
                            interval=interval, reference_date=date(2026, 1, 1))
    multiplier = 1.12 ** (1 / periods)
    expected = 1000 + contribution * sum(multiplier ** year for year in range(1, periods + 1))
    assert rows[-1]["end_balance"] == round(expected, 2)


def test_attribute_edit_and_readers_never_post_or_change_balance(db):
    row = account(db, rate=10)
    fund(db, row)
    member(db, born=date(2000, 1, 1))
    owner = goal(db)
    before = [(leg.id, leg.debit_minor, leg.credit_minor) for leg in db.query(models.JournalEntry)]
    update_account(db, 1, row.id, {"institution": "ideco", "withdrawable_from_age": 60})
    def no_flush(*_):
        pytest.fail("Reading assumptions must not flush a write")
    event.listen(db, "before_flush", no_flush)
    try:
        shelter_breakdown(db, 1)
        get_summary(db, 1)
        get_goal_simulation_context(db, 1, owner)
        simulate_net_worth_forward(db, 1, years=1)
        assert calculate_account_balances(db, [row])[row.id].balances_minor == {"JPY": 1000}
        assert before == [(leg.id, leg.debit_minor, leg.credit_minor) for leg in db.query(models.JournalEntry)]
        assert db.query(models.Transaction).count() == 1
    finally:
        event.remove(db, "before_flush", no_flush)


def test_backup_round_trip_carries_shelter_age_and_missing_return(db):
    row = account(db, institution="ideco", age=63)
    fund(db, row)
    source = db.get(models.Client, 1)
    target = db.get(models.Client, 2)
    document = export_client(db, source)
    assert document["version"] == EXPORT_VERSION == 22
    import_client(db, target, data=document["data"], version=document["version"], manifest=document["manifest"])
    restored = db.query(models.Account).filter_by(client_id=2, name="cash").one()
    assert (restored.institution, restored.withdrawable_from_age, restored.expected_return) == ("ideco", 63, None)
    assert restored.id != row.id
    assert calculate_account_balances(db, [restored])[restored.id].balances_minor == {"JPY": 1000}


def test_old_backup_defaults_to_none_and_no_lock(db):
    row = account(db, institution="ideco", age=60)
    document = export_client(db, db.get(models.Client, 1))
    document.pop("manifest", None)
    document["version"] = 17
    for item in document["data"]["accounts"]:
        item.pop("institution")
        item.pop("withdrawable_from_age")
    import_client(db, db.get(models.Client, 2), data=document["data"], version=document["version"], manifest=None)
    restored = db.query(models.Account).filter_by(client_id=2, name=row.name).one()
    assert (restored.institution, restored.withdrawable_from_age) == ("none", None)


@pytest.mark.parametrize("schema", [AccountCreate, schemas.AccountCreate])
def test_create_schema_rejects_unknown_shelter_and_negative_age(schema):
    with pytest.raises(ValidationError):
        schema(name="口座", account_type="asset", institution="unknown")
    with pytest.raises(ValidationError):
        schema(name="口座", account_type="asset", withdrawable_from_age=-1)


@pytest.mark.parametrize("schema", [AccountUpdate, schemas.AccountUpdate])
def test_update_schema_rejects_unknown_shelter_and_negative_age(schema):
    with pytest.raises(ValidationError):
        schema(institution="unknown")
    with pytest.raises(ValidationError):
        schema(withdrawable_from_age=-1)


@pytest.mark.parametrize("values", [{"institution": "unknown"}, {"institution": None}, {"withdrawable_from_age": -1}])
def test_service_validates_before_write(db, values):
    row = account(db)
    with pytest.raises(Invalid):
        update_account(db, 1, row.id, values)
    assert row.institution == "none" and row.withdrawable_from_age is None


@pytest.mark.parametrize("values", [{"institution": "unknown"}, {"withdrawable_from_age": -1}])
def test_database_enforces_shelter_and_age(db, values):
    db.add(models.Account(client_id=1, name="不正", account_type="asset", **values))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_account_response_serializes_both_attributes_and_nullable_return(db):
    row = account(db, institution="dc_corporate", age=62)
    values = _serialize_account(row, calculate_account_balances(db, [row])[row.id])
    response = AccountResponse.model_validate(values)
    assert (response.institution, response.withdrawable_from_age, response.expected_return) == ("dc_corporate", 62, None)


def test_blend_ignores_overdrawn_accounts(db):
    positive = account(db, rate=10)
    negative = account(db, name="負の残高", institution="nisa_growth", rate=20)
    fund(db, positive, 1000)
    income = db.query(models.Account).filter_by(client_id=1, name="給与").one()
    create_transaction(db, client_id=1, date=date(2020, 1, 1), description="残高", amount_minor=500,
                       currency="JPY", from_account_id=negative.id, to_account_id=income.id)
    assert blended_after_tax_return(db, 1, gross_annual_return=12, tax_rate=20) == 8


def test_foreign_locked_asset_makes_free_cash_condition_unknown(db):
    from app.services import life_event_conditions
    row = account(db, name="外貨年金", institution="ideco", age=60)
    fund(db, row, 12345, "USD")
    person = member(db, born=date(2000, 1, 1))
    owner = goal(db)
    db.add(models.LifeEventCondition(client_id=1, life_event_id=owner.id, metric="free_cash",
                                     comparator="gte", threshold_minor=0))
    db.commit()
    result = life_event_conditions.evaluate(db, 1, owner.id)
    assert result["satisfied"] is None
    assert result["conditions"][0]["actual"] is None
    assert "通貨が異なります" in result["conditions"][0]["reason"]
    db.delete(person)
    db.commit()
    assert life_event_conditions.evaluate(db, 1, owner.id)["satisfied"] is True


@pytest.mark.parametrize("invalid", [{"institution": "unknown"}, {"withdrawable_from_age": -1}])
def test_invalid_backup_is_rejected_before_replacement(db, invalid):
    account(db, institution="ideco", age=60)
    target_account = account(db, name="保持", client_id=2)
    fund(db, target_account, 777)
    document = export_client(db, db.get(models.Client, 1))
    document["data"]["accounts"][0].update(invalid)
    with pytest.raises(Invalid):
        import_client(db, db.get(models.Client, 2), data=document["data"], version=18, manifest=None)
    target_account = db.query(models.Account).filter_by(client_id=2, name="保持").one()
    assert calculate_account_balances(db, [target_account])[target_account.id].balances_minor == {"JPY": 777}
