"""Simulate a scenario account by account: contributions, transfers, yields, loans, and which events happen.

The scenario's 使用口座 (the asset accounts its 積立設定 records name) grow from their
journal balance by the yield in force and receive their 積立 (contributions), calendar
year by calendar year on shared seeded paths: the first row is the rest of this year
(no growth yet), each later row a whole year, so contributions, transfers, events and
withdrawals of one month always fall in the same row. A 口座振替 moves money between
them month by month; when the source holds less, it does not happen or moves what is
there (on_shortage).
Everything else -- other accounts, debts already on the books -- is the residual net worth.

A ライフイベントへの取り崩し takes its amount out of the account in its months. Before the
event's month it hands the money to the residual (where the event's paths still allow
it), so the account falls then and net worth falls when the event is paid. From the
event's month on it pays the event in instalments (e.g. 老後生活 from 2051, ¥100,000 a
month): the event's own payment leaves out what the instalments pay (up to its
amount), and each instalment lowers net worth when it is paid. Instalments before this
month are taken as paid already. An instalment the account cannot pay (on_shortage)
comes from the residual; nothing moves into an account from elsewhere.

An event happens on a path when the event it follows happened there and its
preconditions hold at its date. It is paid from (or arrives in) the residual. A borrowing brings cash in and opens a debt of the same size,
so net worth does not move; its repayments pay a month at a time from their start,
interest accruing on what is left, and happen only where the borrowing did.

The result says how likely each event is to happen and, for an expense, to be
affordable (through its last instalment within the simulated years), which branches most paths take, and the net
worth and account bands. Amounts are in today's money: yields and the residual are
deflated by inflation; contributions, transfers, loans and repayments are fixed in real terms.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from .contribution_plan_service import (
    OPEN_MONTHS, contributed_minor, index_period, monthly_total_minor, occurrence_indexes, of_kind, rate, used_account_ids,
)
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
    return index_period(start.year * 12 + start.month - 1 + offset_months)


def _month(when: date | None) -> int | None:
    return None if when is None else when.year * 12 + when.month - 1


def used_accounts(db: Session, client_id: int, plans) -> list[models.Account]:
    """使用口座: the asset accounts the scenario's 積立設定 records name."""
    ids = used_account_ids(plans)
    if not ids:
        return []
    return db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset", models.Account.id.in_(ids),
    ).order_by(models.Account.id).all()


def _opening(db: Session, client_id: int, accounts: list[models.Account]) -> tuple[dict[int, float], str]:
    """Each used account's balance as one amount in the client's currency, valued like the balance sheet (WP24)."""
    currency = get_client_currency(db, client_id)
    values = calculate_account_balances(db, accounts) if accounts else {}
    return {account.id: values[account.id].balance for account in accounts}, currency


def _row_index(today: date, when: date | None) -> int | None:
    if when is None:
        return None
    return max(0, when.year - today.year)


def _take(balance: np.ndarray, each: float, times: int, on_shortage: str | None) -> np.ndarray:
    """What an account gives for `times` movements of `each`: whole movements it can cover (skip), or what it holds (partial)."""
    if times <= 0 or each <= 0:
        return np.zeros_like(balance)
    held = np.maximum(balance, 0.0)
    if on_shortage == "skip":
        return np.clip(np.floor(held / each), 0, times) * each
    return np.minimum(held, each * times)


def instalments(plans, events: list[ScenarioEvent], currency: str) -> dict[int, list[tuple[int, float]]]:
    """{event_id: [(month index, amount)]}: the withdrawals from an expense's month on, which pay it in
    instalments, oldest first, up to the event's amount (past months included: they are paid already)."""
    by_id = {event.id: event for event in events if event.direction == "expense" and event.resolved_date is not None}
    found: dict[int, list[tuple[int, float]]] = {}
    for plan in of_kind(plans, "withdrawal"):
        event = by_id.get(plan.life_event_id)
        if event is None:
            continue
        start = _month(event.resolved_date)
        each = Money(plan.amount_minor, currency).to_float()
        found.setdefault(event.id, []).extend((month, each) for month in occurrence_indexes(plan, start, start + OPEN_MONTHS))
    for event_id, rows in found.items():
        left, kept = by_id[event_id].target_amount, []
        for month, each in sorted(rows):
            if left <= 0:
                break
            kept.append((month, min(each, left)))
            left -= min(each, left)
        found[event_id] = kept
    return found


def simulate(db: Session, client_id: int, scenario: models.LifeScenario) -> dict:
    today = date.today()
    years = max(1, min(scenario.horizon_years, 60))
    config = db.query(models.SimulationConfig).filter_by(client_id=client_id).first()
    volatility = (config.volatility if config and config.volatility is not None else 15.0) / 100.0
    tax = (config.tax_rate if config and config.tax_rate is not None else 20.0) / 100.0
    inflation = scenario.inflation / 100.0
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=scenario.id).all()
    events = walk(db, client_id, scenario.id)
    accounts = used_accounts(db, client_id, plans)
    opening, currency = _opening(db, client_id, accounts)
    current_month = today.year * 12 + today.month - 1
    last_month = (today.year + years) * 12 + 11
    event_months = {event.id: _month(event.resolved_date) for event in events}
    # 取り崩し by calendar row: (record, movements before the event's month, instalments from it on).
    taken_by_row: dict[int, list[tuple[models.ScenarioContributionPlan, int, int]]] = {}
    for plan in of_kind(plans, "withdrawal"):
        due = event_months.get(plan.life_event_id)
        counts: dict[int, list[int]] = {}
        for month in occurrence_indexes(plan, current_month, last_month):
            pair = counts.setdefault(month // 12 - today.year, [0, 0])
            pair[1 if due is not None and month >= due else 0] += 1
        for row, (before, after) in counts.items():
            taken_by_row.setdefault(row, []).append((plan, before, after))
    later = instalments(plans, events, currency)
    # The event's own payment leaves out every instalment; those before this month are paid already.
    paid_later = {event_id: sum(amount for _, amount in rows) for event_id, rows in later.items()}
    still_owed = {event_id: sum(amount for month, amount in rows if month >= current_month) for event_id, rows in later.items()}
    transfers = sorted(of_kind(plans, "transfer"), key=lambda plan: (plan.start_period, plan.id or 0))
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
    owed: dict[int, np.ndarray] = {}
    judged: dict[int, dict] = {}
    worth = np.empty((PATHS, years + 1))
    account_rows = {account.id: np.empty((PATHS, years + 1)) for account in accounts}

    def move(event: ScenarioEvent, amount: np.ndarray) -> None:
        nonlocal residual
        residual = residual + amount

    def withdraw(index: int) -> None:
        """This year's ライフイベントへの取り崩し: account to residual up to the event, instalments after it."""
        nonlocal residual
        for plan, before, after in taken_by_row.get(index, []):
            if plan.account_id not in balances:
                continue
            each = Money(plan.amount_minor, currency).to_float()
            balance = balances[plan.account_id]
            if before:
                runs = executed.get(plan.life_event_id, np.ones(PATHS, dtype=bool))
                moved = np.where(runs, _take(balance, each, before, plan.on_shortage), 0.0)
                balance = balance - moved
                residual = residual + moved
            if after:
                runs = executed.get(plan.life_event_id, np.zeros(PATHS, dtype=bool))
                due = np.where(runs, np.minimum(each * after, owed.get(plan.life_event_id, np.zeros(PATHS))), 0.0)
                got = np.where(runs, _take(balance, each, after, plan.on_shortage), 0.0)
                covered = np.minimum(got, due)
                balance = balance - got
                # What the account cannot pay comes from the residual; what it gives beyond the instalment stays there.
                residual = residual + (got - covered) - (due - covered)
                if plan.life_event_id in owed:
                    owed[plan.life_event_id] = owed[plan.life_event_id] - due
                if plan.life_event_id in funded:
                    # Affordability is watched while instalments are due, not after the last one.
                    funded[plan.life_event_id] &= np.where(due > 0, net_of(balance, plan.account_id) >= 0, True)
            balances[plan.account_id] = balance

    def net() -> np.ndarray:
        return sum(balances.values(), residual) - sum(debts.values(), np.zeros(PATHS))

    def net_of(balance: np.ndarray, account_id: int) -> np.ndarray:
        return net() - balances[account_id] + balance

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
            if event.direction == "expense":
                later = paid_later.get(event.id, 0.0)
                move(event, -np.where(runs, event.target_amount - later, 0.0))
                owed[event.id] = np.where(runs, still_owed.get(event.id, 0.0), 0.0)
            elif event.direction in ("income", "borrowing"):
                amount = np.where(runs, event.target_amount, 0.0)
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
        withdraw(index)

    def repay(index: int) -> None:
        """Pay this calendar year's months of every running repayment, interest first."""
        year = today.year + index
        for event, runs in schedules:
            start = event.resolved_date.year * 12 + event.resolved_date.month - 1
            months = range(max(start, year * 12, current_month), min(start + (event.repeat_count or 1), (year + 1) * 12))
            borrowing = by_id.get(event.borrowing_event_id) if event.borrowing_event_id in debts else None
            interest = (borrowing.interest_rate or 0.0) / 100.0 / 12.0 if borrowing is not None else 0.0
            for _ in months:
                if borrowing is not None:
                    due = debts[borrowing.id] * (1 + interest)
                    pay = np.where(runs, np.minimum(event.target_amount, due), 0.0)
                    debts[borrowing.id] = np.where(runs, due - pay, debts[borrowing.id])
                else:
                    pay = np.where(runs, event.target_amount, 0.0)
                move(event, -pay)

    def transfer(first: int, last: int) -> None:
        """This row's 口座振替 month by month (oldest record first within a month), so money one transfer
        brings in can go on with a later one; a short source skips or moves what it holds."""
        movable = [plan for plan in transfers if plan.account_id in balances and plan.to_account_id in balances]
        for month in range(first, last + 1):
            for plan in movable:
                if not occurrence_indexes(plan, month, month):
                    continue
                moved = _take(balances[plan.account_id], Money(plan.amount_minor, currency).to_float(), 1, plan.on_shortage)
                balances[plan.account_id] = balances[plan.account_id] - moved
                balances[plan.to_account_id] = balances[plan.to_account_id] + moved

    def record(index: int) -> None:
        worth[:, index] = net()
        for account_id, rows in account_rows.items():
            rows[:, index] = balances[account_id]

    def step(index: int, shock: np.ndarray | None) -> None:
        """One calendar row: this row's contributions (with a year's growth after the first row), transfers, events."""
        nonlocal residual
        first, last = max(current_month, (today.year + index) * 12), (today.year + index) * 12 + 11
        for account in accounts:
            contribution = Money(sum(contributed_minor(plans, account.id, index_period(month)) for month in range(first, last + 1)), currency).to_float()
            if shock is None:
                # The rest of this year: no growth counted yet.
                balances[account.id] = balances[account.id] + contribution
                continue
            yearly = rate(plans, account.id, index_period(first), scenario.annual_return)
            real = ((yearly * (1 - tax) if yearly > 0 else yearly) / 100.0) - inflation
            growth = real + (shock if yearly > CASH_LIKE_RETURN else 0.0)
            # Contributions arrive through the year: on average they earn half a year.
            balances[account.id] = balances[account.id] * (1 + growth) + contribution * (1 + growth / 2)
        transfer(first, last)
        if shock is not None:
            residual = residual * (1 - inflation)
        happen(index)
        record(index)

    step(0, None)
    for index in range(1, years + 1):
        step(index, rng.normal(0, volatility, PATHS))

    demand = aggregate_event_demand_by_year(
        [(event.resolved_date, event.target_amount - paid_later.get(event.id, 0.0)) for event in events if event.direction == "expense"]
        + [(date(month // 12, month % 12 + 1, 1), amount) for rows in later.values() for month, amount in rows if month >= current_month],
        years,
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
        "monthly_contribution": Money(monthly_total_minor(plans, _period(today, 0)), currency).to_float(),
    }
