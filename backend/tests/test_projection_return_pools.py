"""Only positive holdings earn account returns; debts retain nominal principal."""
from datetime import date

import numpy as np
import pytest

from app.services import life_scenario_service as scenarios
from app.services.institution_service import blended_after_tax_return, positive_asset_balance
from app.services.ledger_service import create_account, create_transaction
from app.services.strategy_service import PROJECTION_SEED, simulate_net_worth_forward_with_paths
from test_life_scenarios import account, api, config, db, request


def holding(db, name, balance, rate=0, kind="asset"):
    row = account(db, name=name, rate=rate, kind=kind)
    counter = create_account(db, 1, {"name": f"{name} opening", "account_type": "equity"})
    debit_balance = balance > 0 if kind == "asset" else balance < 0
    source, target = (counter, row) if debit_balance else (row, counter)
    create_transaction(db, client_id=1, date=date(2020, 1, 1), description="Opening balance",
                       amount_minor=abs(balance), currency="JPY", from_account_id=source.id, to_account_id=target.id)
    db.commit()
    return row


@pytest.mark.parametrize("monthly_savings", [0, 50000])
def test_overdrawn_client_savings_override_strictly_raises_30_year_p50(db, api, monthly_savings):
    config(db, monthly_savings_minor=monthly_savings)
    for name, balance in (("bank", -65000), ("cash", -6), ("investment", -10000)):
        holding(db, name, balance)
    savings = holding(db, "savings", 20000)
    saved = request(api, "POST", "/life-scenarios", json={"name": "Regression"}).json()
    base = f'/life-scenarios/{saved["id"]}'
    assert request(api, "PUT", base, json={"horizon_years": 30}).status_code == 200
    compared = []
    for rate in (0, 8):
        response = request(api, "PUT", base + "/account-returns",
                           json={"returns": [{"account_id": savings.id, "annual_return": rate}]})
        assert response.status_code == 200
        compared.append(request(api, "GET", f'/life-scenarios/compare?ids={saved["id"]}').json()["scenarios"][0]["projection"])
    low, high = compared
    assert low[0]["p50"] == high[0]["p50"] == -55006
    assert all(h["p50"] >= l["p50"] for l, h in zip(low, high))
    assert high[-1]["p50"] > low[-1]["p50"]
    assert savings.expected_return == 0


@pytest.mark.parametrize("seed", [17, 42, 103])
@pytest.mark.parametrize("net_sign", [-1, 1])
def test_raising_any_account_rate_never_lowers_p50_for_seeded_mixed_balances(db, seed, net_sign):
    rng = np.random.default_rng(seed)
    positive = rng.integers(10000, 100000, 4)
    negative = -rng.integers(10000, 100000, 4)
    # Exercise both signs of net worth while retaining several earning accounts.
    if net_sign < 0:
        negative *= 10
    else:
        positive *= 10
    balances = np.concatenate((positive, negative, [0]))
    rates = rng.uniform(0, 8, len(balances))
    accounts = [holding(db, f"mix {i}", int(balance), float(rate)) if balance else account(db, name="empty", rate=float(rate))
                for i, (balance, rate) in enumerate(zip(balances, rates))]
    config(db, monthly_savings_minor=1000)
    saved = scenarios.create(db, 1, "Mix")
    scenarios.update(db, 1, saved.id, {"horizon_years": 30})
    baseline = scenarios.project(db, 1, saved)["projection"][-1]["p50"]
    assert positive_asset_balance(db, 1) == sum(positive)
    for row, balance, rate in zip(accounts, balances, rates):
        scenarios.replace_account_returns(db, 1, saved.id, [{"account_id": row.id, "annual_return": float(rate) + 8}])
        raised = scenarios.project(db, 1, saved)["projection"][-1]["p50"]
        assert raised >= baseline, (seed, net_sign, balance, baseline, raised)
        if balance > 0:
            assert raised > baseline
        else:
            assert raised == baseline


@pytest.mark.parametrize("annual_return", [0, 8, 25])
@pytest.mark.parametrize("inflation", [0, 2, 5])
def test_liability_only_deflates_without_investment_return_or_market_shock(db, annual_return, inflation):
    holding(db, "loan", 100000, kind="liability")
    config(db, volatility=35, monthly_savings_minor=0)
    bands, paths = simulate_net_worth_forward_with_paths(
        db, 1, years=30, annual_return=annual_return, inflation=inflation, include_event_income=False,
    )
    expected = -100000 * (1 - inflation / 100) ** np.arange(31)
    np.testing.assert_allclose(paths, np.broadcast_to(expected, paths.shape))
    nominal_in_real_terms = -100000.
    for row in bands:
        assert row["p10"] == row["p50"] == row["p90"] == round(nominal_in_real_terms)
        nominal_in_real_terms *= 1 - inflation / 100


def test_positive_assets_and_debt_use_one_shared_draw_for_earning_and_contributions(db):
    holding(db, "savings", 20000, rate=8)
    holding(db, "overdraft", -75006, rate=99)
    config(db, monthly_savings_minor=1000, volatility=15)
    bands, paths = simulate_net_worth_forward_with_paths(
        db, 1, years=4, annual_return=5, inflation=2, include_event_income=False,
    )
    rng = np.random.default_rng(PROJECTION_SEED)
    earning = np.full(1200, 20000.)
    residual = -75006.
    invested = np.zeros(1200)
    for year in range(1, 5):
        shock = rng.normal(0, .15, 1200)
        earning *= 1 + .044 + shock
        residual *= .98
        invested = (invested + 12000) * (1 + .02 + shock)
        np.testing.assert_array_equal(paths[:, year], earning + residual + invested)
        assert [bands[year][band] for band in ("p10", "p50", "p90")] == [
            round(value) for value in np.percentile(paths[:, year], [10, 50, 90])]


@pytest.mark.parametrize("balance", [-1000, 0])
def test_no_positive_balance_keeps_taxed_gross_fallback(db, balance):
    if balance:
        row = holding(db, "overdraft", balance, rate=99)
    else:
        row = account(db, rate=99)
    assert positive_asset_balance(db, 1) == 0
    assert blended_after_tax_return(db, 1, gross_annual_return=10, tax_rate=25, account_returns={row.id: 50}) == 7.5


def test_inactive_balance_earns_nothing_and_its_rate_changes_nothing(db, api):
    # The balance sheet the projection starts from counts active accounts only,
    # so an inactive holding must not join the earning pool: its growth would be
    # a gain on money the forecast never started with.
    config(db, monthly_savings_minor=0)
    holding(db, "active", 50000)
    dormant = holding(db, "dormant", 80000)
    dormant.is_active = False
    db.commit()
    assert positive_asset_balance(db, 1) == 50000
    saved = request(api, "POST", "/life-scenarios", json={"name": "Dormant"}).json()
    base = f'/life-scenarios/{saved["id"]}'
    compared = []
    for rate in (0, 9):
        assert request(api, "PUT", base + "/account-returns",
                       json={"returns": [{"account_id": dormant.id, "annual_return": rate}]}).status_code == 200
        compared.append(request(api, "GET", f'/life-scenarios/compare?ids={saved["id"]}').json()["scenarios"][0]["projection"])
    low, high = compared
    assert [row["p50"] for row in low] == [row["p50"] for row in high]
    assert low[0]["p50"] == 50000
