"""Simulate a scenario account by account: contributions, yields, loans, and which events happen.

The scenario's 使用口座 (the asset accounts its 積立設定 names) grow from their journal
balance by the yield in force and receive the monthly amounts in force (a negative
amount withdraws), year by year on shared seeded paths. Everything else -- other
accounts, debts already on the books -- is the residual net worth.

An event happens on a path when the event it follows happened there and its
preconditions hold at its date. An expense leaves its account (or the residual), an
inflow arrives there. A borrowing brings cash in and opens a debt of the same size,
so net worth does not move; its repayments pay a month at a time from their start,
interest accruing on what is left, and happen only where the borrowing did.

The result says how likely each event is to happen and, for an expense, to be
affordable, which branches most paths take, and the net worth and account bands.
Amounts are in today's money: yields and the residual are deflated by inflation;
contributions, loans and repayments are fixed in real terms.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from .contribution_plan_service import resolve
from .fx_service import get_client_currency
from .ledger_valuation import calculate_account_balances
from .life_event_conditions import PathJudge
from .life_event_walk import ScenarioEvent, aggregate_event_demand_by_year, walk
from .reporting_service import get_balance_sheet

PROJECTION_SEED = 42
PATHS = 1200
# An account yielding no more than this behaves like cash: no market shock.
CASH_LIKE_RETURN = 1.0


def _period(start: date, offset_months: int) -> str:
    index = start.year * 12 + start.month - 1 + offset_months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def used_accounts(db: Session, client_id: int, plans) -> list[models.Account]:
    """使用口座: the asset accounts the scenario's 積立設定 names."""
    ids = {plan.account_id for plan in plans}
    if not ids:
        return []
    return db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset", models.Account.id.in_(ids),
    ).order_by(models.Account.id).all()


def _opening(db: Session, client_id: int, accounts: list[models.Account]) -> tuple[dict[int, float], str]:
    currency = get_client_currency(db, client_id)
    values = calculate_account_balances(db, accounts) if accounts else {}
    return {account.id: Money(values[account.id].balances_minor.get(currency, 0), currency).to_float()
            for account in accounts}, currency


def _row_index(today: date, when: date | None) -> int | None:
    if when is None:
        return None
    return max(0, when.year - today.year)


def simulate(db: Session, client_id: int, scenario: models.LifeScenario) -> dict:
    today = date.today()
    years = max(1, min(scenario.horizon_years, 60))
    config = db.query(models.SimulationConfig).filter_by(client_id=client_id).first()
    volatility = (config.volatility if config and config.volatility is not None else 15.0) / 100.0
    tax = (config.tax_rate if config and config.tax_rate is not None else 20.0) / 100.0
    inflation = scenario.inflation / 100.0
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=scenario.id).all()
    accounts = used_accounts(db, client_id, plans)
    opening, currency = _opening(db, client_id, accounts)
    events = walk(db, client_id, scenario.id)
    by_id = {event.id: event for event in events}
    parents = {link.to_event_id: link.from_event_id for link in db.query(models.LifeEventLink).filter(
        models.LifeEventLink.id.in_([event.incoming_link_id for event in events if event.incoming_link_id]))}
    judge = PathJudge(db, client_id, [event.id for event in events])

    rng = np.random.default_rng(PROJECTION_SEED)
    balances = {account.id: np.full(PATHS, opening[account.id]) for account in accounts}
    residual = np.full(PATHS, (get_balance_sheet(db, client_id=client_id).get("net_worth", 0.0) or 0.0) - sum(opening.values()))
    debts: dict[int, np.ndarray] = {}
    schedules: list[tuple[ScenarioEvent, np.ndarray]] = []
    by_row: dict[int, list[ScenarioEvent]] = {}
    for event in events:
        index = _row_index(today, event.resolved_date)
        if index is not None and index <= years:
            by_row.setdefault(index, []).append(event)
    executed: dict[int, np.ndarray] = {}
    funded: dict[int, np.ndarray] = {}
    judged: dict[int, dict] = {}
    worth = np.empty((PATHS, years + 1))
    account_rows = {account.id: np.empty((PATHS, years + 1)) for account in accounts}
    current_month = today.year * 12 + today.month - 1

    def move(event: ScenarioEvent, amount: np.ndarray) -> None:
        nonlocal residual
        if event.account_id in balances:
            balances[event.account_id] = balances[event.account_id] + amount
        else:
            residual = residual + amount

    def net() -> np.ndarray:
        return sum(balances.values(), residual) - sum(debts.values(), np.zeros(PATHS))

    def happen(index: int) -> None:
        # Repayments after the rest of the year, so the borrowing they repay is known.
        row = by_row.get(index, [])
        for event in [item for item in row if item.direction != "repayment"] + [item for item in row if item.direction == "repayment"]:
            truth, details = judge.judge(event.id, event.resolved_date, net(), balances)
            runs = truth != -1  # unknown information does not stop the plan
            parent = parents.get(event.id)
            if parent is not None:
                runs &= executed.get(parent, np.zeros(PATHS, dtype=bool))
            if event.direction == "repayment" and event.borrowing_event_id in by_id:
                runs &= executed.get(event.borrowing_event_id, np.zeros(PATHS, dtype=bool))
            amount = np.where(runs, event.target_amount, 0.0)
            if event.direction == "expense":
                move(event, -amount)
            elif event.direction in ("income", "borrowing"):
                move(event, amount)
                if event.direction == "borrowing":
                    debts[event.id] = amount
            else:
                schedules.append((event, runs))
            executed[event.id] = runs
            if event.direction == "expense":
                funded[event.id] = runs & (net() >= 0)
            if judge.has_conditions(event.id):
                judged[event.id] = {"event_id": event.id, "event_name": event.name,
                                    "judged_at": event.resolved_date.isoformat() if event.resolved_date else None,
                                    "mode": judge.modes.get(event.id, "all"),
                                    "probability": None if np.any(truth == 0) else float(np.mean(truth == 1)),
                                    "conditions": details}
        repay(index)

    def repay(index: int) -> None:
        """Pay this calendar year's months of every running repayment, interest first."""
        year = today.year + index
        for event, runs in schedules:
            start = event.resolved_date.year * 12 + event.resolved_date.month - 1
            months = range(max(start, year * 12, current_month), min(start + (event.repeat_count or 1), (year + 1) * 12))
            borrowing = by_id.get(event.borrowing_event_id) if event.borrowing_event_id in debts else None
            rate = (borrowing.interest_rate or 0.0) / 100.0 / 12.0 if borrowing is not None else 0.0
            for _ in months:
                if borrowing is not None:
                    due = debts[borrowing.id] * (1 + rate)
                    pay = np.where(runs, np.minimum(event.target_amount, due), 0.0)
                    debts[borrowing.id] = np.where(runs, due - pay, debts[borrowing.id])
                else:
                    pay = np.where(runs, event.target_amount, 0.0)
                move(event, -pay)

    def record(index: int) -> None:
        worth[:, index] = net()
        for account_id, rows in account_rows.items():
            rows[:, index] = balances[account_id]

    happen(0)
    record(0)
    for index in range(1, years + 1):
        shock = rng.normal(0, volatility, PATHS)
        first_month = 12 * (index - 1)
        for account in accounts:
            contribution_minor = sum(resolve(plans, account.id, _period(today, first_month + month), scenario.annual_return)[0]
                                     for month in range(12))
            rate = resolve(plans, account.id, _period(today, first_month), scenario.annual_return)[1]
            real = ((rate * (1 - tax) if rate > 0 else rate) / 100.0) - inflation
            growth = real + (shock if rate > CASH_LIKE_RETURN else 0.0)
            contribution = Money(contribution_minor, currency).to_float()
            # Contributions arrive through the year: on average they earn half a year.
            balances[account.id] = balances[account.id] * (1 + growth) + contribution * (1 + growth / 2)
        residual = residual * (1 - inflation)
        happen(index)
        record(index)

    demand = aggregate_event_demand_by_year(
        [(event.resolved_date, event.target_amount) for event in events if event.direction == "expense"], years,
        income_events=[(event.resolved_date, event.target_amount) for event in events if event.direction == "income"],
    )
    projection = [{"year": today.year + index, **{band: round(float(value), 0) for band, value in zip(
        ("p10", "p50", "p90"), np.percentile(worth[:, index], [10, 50, 90]))},
        "cumulative_target": demand[index]["cumulative_target"], "cumulative_income": demand[index]["cumulative_income"]}
        for index in range(years + 1)]
    names = {account.id: account.name for account in accounts}
    # The likely path: the events that happen on at least half of the paths.
    taken = {event_id for event_id, runs in executed.items() if np.mean(runs) >= 0.5}
    return {
        "projection": projection,
        "events": [{**asdict(event), "executed_probability": round(float(np.mean(executed[event.id])), 4) if event.id in executed else None,
                    "funded_probability": round(float(np.mean(funded[event.id])), 4) if event.id in funded else None,
                    "on_likely_path": event.id in taken}
                   for event in events],
        "conditions": list(judged.values()),
        "likely_path": {"event_ids": sorted(taken),
                        "link_ids": sorted(event.incoming_link_id for event in events
                                           if event.incoming_link_id and event.id in taken and parents.get(event.id) in taken)},
        "accounts": [{"account_id": account_id, "name": names[account_id],
                      "p50": [round(float(value), 0) for value in np.median(rows, axis=0)]}
                     for account_id, rows in account_rows.items()],
        "monthly_contribution": Money(sum(resolve(plans, account.id, _period(today, 0), scenario.annual_return)[0]
                                          for account in accounts), currency).to_float(),
    }
