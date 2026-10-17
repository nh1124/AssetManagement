"""Shared goal calculation primitives.

This module is retained as the implementation home for projection math during the
transition from the old all-in-one Strategy workspace. Domain callers should prefer
goal_service or simulation_service so UI responsibilities stay decoupled.
"""
from __future__ import annotations

from sqlalchemy.orm import Session
from datetime import date
from typing import Any, List, Optional, Tuple
import math
import numpy as np
from .. import models
from .ledger_valuation import calculate_account_valued_balance
from .reporting_service import get_balance_sheet, get_net_worth_history
from .institution_service import blended_after_tax_return, positive_asset_balance
from .goal_service import goal_events_query, list_goals, story_events_query
from . import goal_budget_record
from .product_reserve_service import reserve_totals_by_capsule

PRIORITY_WEIGHTS = {1: 3, 2: 2, 3: 1}
DEFAULT_NEAR_YEARS = 5

# Every projection draws from this one seed, so a figure does not move when
# nothing about the plan moved, and two scenarios can be read as differing by
# the assumption that differs between them rather than by sampling noise.
PROJECTION_SEED = 42


def calculate_current_funded_and_weighted_return(event: models.LifeEvent, db: Optional[Session] = None) -> Tuple[float, float]:
    """Funded amount and weighted return from client-currency journal claims."""
    from sqlalchemy.orm import object_session
    from .capsule_service import claimed_minor
    from .fx_service import get_client_currency
    from ..domain.money import Money
    # An expected receipt has no savings requirement, even if old claims remain linked.
    if event.direction == "income":
        return 0.0, 5.0
    db = db or object_session(event)
    if db is None:
        return 0.0, 5.0
    currency = get_client_currency(db, event.client_id)
    total_funded = 0.0
    weighted_return_sum = 0.0
    for capsule in event.capsules or []:
        account_ids = {row[0] for row in db.query(models.JournalEntry.account_id).filter(
            models.JournalEntry.capsule_id == capsule.id,
        ).distinct()}
        for account_id in account_ids:
            held = Money(claimed_minor(db, event.client_id, capsule.id, account_id).get(currency, 0), currency).to_float()
            if held > 0:
                account = db.get(models.Account, account_id)
                total_funded += held
                weighted_return_sum += held * (account.expected_return or 0.0)
    return total_funded, weighted_return_sum / total_funded if total_funded > 0 else 5.0


def calculate_current_funded(event: models.LifeEvent, db: Optional[Session] = None) -> float:
    total, _ = calculate_current_funded_and_weighted_return(event, db)
    return total


def calculate_projection(
    current_funded: float,
    monthly_savings: float,
    years_remaining: float,
    annual_return: float = 5.0,
    *, contribution_annual_return: float | None = None,
) -> float:
    """
    Calculate projected future value using the loop-based 'Roadmap' logic.
    Year End Balance = (Start Balance + Annual Contribution) * (1 + Annual Return Rate)
    """
    if years_remaining <= 0:
        return current_funded
    
    r = annual_return / 100.0
    contribution_rate = (annual_return if contribution_annual_return is None else contribution_annual_return) / 100.0
    # The simulation rate describes how new savings will be invested;
    # existing holdings already have their own rates.
    held = current_funded
    invested = 0.0
    annual_contribution = monthly_savings * 12
    
    full_years = int(years_remaining)
    partial_year = years_remaining - full_years
    
    # Loop through full years
    for _ in range(full_years):
        held *= 1 + r
        invested = (invested + annual_contribution) * (1 + contribution_rate)
        
    # Add partial year if any
    if partial_year > 0:
        held *= 1 + r * partial_year
        invested = (invested + annual_contribution * partial_year) * (1 + contribution_rate * partial_year)
        
    return held + invested


def _period_contribution_from_schedule(
    schedule: list[dict],
    period_start: date,
    period_end: date,  # exclusive
) -> float:
    """Return the actual total contribution for a specific period from the schedule.

    monthly  → amount once per calendar month that falls in [period_start, period_end)
    yearly   → amount once per calendar year when the bonus month falls in the period
    one_time → amount if the specified date falls in the period
    """
    total = 0.0
    for item in schedule:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        amount = _coerce_schedule_amount(item.get("amount"))
        if amount <= 0:
            continue

        if kind == "monthly":
            # Count distinct months in [period_start, period_end)
            y, m = period_start.year, period_start.month
            while date(y, m, 1) < period_end:
                month_start = date(y, m, 1)
                month_end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
                if _schedule_period_overlaps(item, month_start, month_end):
                    total += amount
                m += 1
                if m > 12:
                    m = 1
                    y += 1
        elif kind == "yearly":
            bonus_month = int(item.get("month") or 6)
            for year in range(period_start.year, period_end.year + 1):
                try:
                    bonus_date = date(year, bonus_month, 1)
                except (ValueError, TypeError):
                    continue
                if period_start <= bonus_date < period_end and _schedule_date_is_active(item, bonus_date):
                    total += amount
        elif kind == "one_time":
            item_date = _coerce_schedule_date(item.get("date"))
            if item_date and period_start <= item_date < period_end:
                total += amount
    return total


def _coerce_schedule_amount(value: Any) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, amount)


def _coerce_schedule_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _schedule_date_is_active(item: dict[str, Any], occurrence_date: date) -> bool:
    start = _coerce_schedule_date(item.get("start_date"))
    end = _coerce_schedule_date(item.get("end_date"))
    if start and occurrence_date < start:
        return False
    if end and occurrence_date > end:
        return False
    return True


def _schedule_period_overlaps(item: dict[str, Any], period_start: date, period_end: date) -> bool:
    start = _coerce_schedule_date(item.get("start_date"))
    end = _coerce_schedule_date(item.get("end_date"))
    if start and period_end <= start:
        return False
    if end and period_start > end:
        return False
    return True


def _schedule_uses_effective_dates(contribution_schedule: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("kind") in {"monthly", "yearly"}
        and (item.get("start_date") or item.get("end_date"))
        for item in contribution_schedule
    )


def monthly_equivalent_from_contribution_schedule(
    contribution_schedule: list[dict[str, Any]] | None,
    reference_date: date,
    target_date: date,
) -> float | None:
    """Convert flexible contribution assumptions into a monthly equivalent.

    Existing projection math allocates one shared savings pool across goals by
    priority. To keep that accounting model stable, bonus and one-time plans are
    normalized over each goal's remaining period before priority allocation.
    """
    if not contribution_schedule:
        return None

    horizon_years = max((target_date - reference_date).days / 365.25, 1 / 12)
    total = 0.0
    has_valid_item = False
    uses_effective_dates = _schedule_uses_effective_dates(contribution_schedule)

    if uses_effective_dates:
        has_valid_item = any(
            isinstance(item, dict)
            and item.get("kind") in {"monthly", "yearly", "one_time"}
            and _coerce_schedule_amount(item.get("amount")) > 0
            for item in contribution_schedule
        )
        if not has_valid_item:
            return None
        total = _period_contribution_from_schedule(contribution_schedule, reference_date, target_date)
        return total / horizon_years / 12

    for item in contribution_schedule:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        amount = _coerce_schedule_amount(item.get("amount"))
        if amount <= 0:
            continue

        if kind == "monthly":
            total += amount * 12 * horizon_years
            has_valid_item = True
        elif kind == "yearly":
            total += amount * horizon_years
            has_valid_item = True
        elif kind == "one_time":
            item_date = _coerce_schedule_date(item.get("date"))
            if item_date is None or reference_date <= item_date <= target_date:
                total += amount
                has_valid_item = True

    if not has_valid_item:
        return None
    return total / horizon_years / 12


def _months_until(start: date, target: date) -> int:
    return (target.year - start.year) * 12 + (target.month - start.month)


def event_monthly_allocation(
    db: Session, client_id: int, event: models.LifeEvent, total: float, evaluation_date: date,
    *, use_record: bool = True,
) -> tuple[float, str]:
    """What this event receives each month out of the story's monthly savings, and why.

    The same breakdown the budget reflection writes, so event progress, milestones
    and the budget describe one plan:
    - a goal event in the applied reflection covering this month receives exactly
      what the budget was told for it ("reflection");
    - otherwise ("rule"), a near event (within the reflection's range, five years by
      default) receives its shortfall over the remaining months, as cash in its
      capsule, and a far event a priority share of what remains; an event left to
      simulation only (試算のみ) receives nothing. When near events need more than
      the savings, they share the savings in proportion to need and far events get
      nothing, so progress shows the shortfall instead of a plan nobody can fund.
    The rule does not judge preconditions; the reflection does, when it is applied.
    """
    if (event.archived_at is not None or event.direction != "expense"
            or event.budget_reflection_effective == "simulation_only"):
        # A called-off, income or simulation-only event receives nothing, whatever was recorded.
        return 0.0, "rule"
    near_years: int | None = DEFAULT_NEAR_YEARS
    latest = goal_budget_record.latest(db, client_id)
    if latest is not None and latest.scenario_id == event.scenario_id:
        near_years = (latest.options or {}).get("near_years", DEFAULT_NEAR_YEARS)
    record = goal_budget_record.covering(db, client_id, evaluation_date.strftime("%Y-%m"))
    if use_record and record is not None and record.scenario_id == event.scenario_id:
        near_years = (record.options or {}).get("near_years", DEFAULT_NEAR_YEARS)
        for row in record.events or []:
            if row.get("lineage") == event.lineage:
                return float(row.get("allocation") or 0.0), "reflection"
    story = [item for item in story_events_query(db, client_id, event).filter(
        models.LifeEvent.direction == "expense",
    ).all() if item.budget_reflection_effective != "simulation_only"]
    if all(item.id != event.id for item in story):
        # A called-off or simulation-only event keeps its saved money but no longer competes.
        return 0.0, "rule"

    def near(item: models.LifeEvent) -> bool:
        return near_years is None or _months_until(evaluation_date, item.target_date) < near_years * 12

    def required(item: models.LifeEvent) -> float:
        months = _months_until(evaluation_date, item.target_date)
        if months < 0:
            return 0.0
        funded = calculate_current_funded_and_weighted_return(item, db)[0]
        return max(0.0, (item.target_amount or 0.0) - funded) / max(1, months)

    # Consumables and fixed assets set aside their reserve first, as the reflection does.
    reserves = sum(row["monthly"] for row in reserve_totals_by_capsule(db, client_id, evaluation_date).values())
    available = max(0.0, total - reserves)
    near_total = sum(required(item) for item in story if near(item))
    if near(event):
        own = required(event)
        return (own if near_total <= available else available * own / near_total), "rule"
    pool = max(0.0, available - near_total)
    far = [item for item in story if not near(item)]
    weights = sum(PRIORITY_WEIGHTS.get(item.priority, 1) for item in far) or 1
    return pool * PRIORITY_WEIGHTS.get(event.priority, 1) / weights, "rule"


def get_goal_simulation_context(
    db: Session,
    client_id: int,
    event: models.LifeEvent,
    annual_return: float | None = None,
    inflation: float | None = None,
    monthly_savings: float | None = None,
    reference_date: date | None = None,
    contribution_schedule: list[dict[str, Any]] | None = None,
    allocation_mode: str = "weighted",
) -> dict:
    """Return the normalized simulation inputs used by goal projections."""
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()

    base_annual_return = annual_return
    if base_annual_return is None:
        base_annual_return = config.annual_return if config else 5.0

    base_inflation = inflation
    if base_inflation is None:
        base_inflation = config.inflation_rate if config else 2.0

    # The event's own scenario carries its savings; the client setting is the default.
    scenario = db.get(models.LifeScenario, event.scenario_id) if event.scenario_id else None
    if scenario is not None and scenario.monthly_savings is not None:
        default_monthly_savings = scenario.monthly_savings
    else:
        default_monthly_savings = config.monthly_savings if config else 50000.0
    base_monthly_savings = default_monthly_savings if monthly_savings is None else monthly_savings

    evaluation_date = reference_date or date.today()
    schedule_monthly = monthly_equivalent_from_contribution_schedule(
        contribution_schedule,
        evaluation_date,
        event.target_date,
    )
    if schedule_monthly is not None:
        base_monthly_savings = schedule_monthly

    # Savings are shared within one story by the breakdown the budget reflection
    # uses. "direct" sends the whole amount to this event (a what-if for one goal).
    # The recorded reflection describes the default savings only; a schedule or an
    # explicit what-if amount is divided by the rule instead.
    if allocation_mode == "direct":
        in_story = event.archived_at is None and event.direction == "expense"
        allocated_monthly_savings = base_monthly_savings if in_story else 0.0
        allocation_source = "direct"
    else:
        what_if = schedule_monthly is not None or abs(base_monthly_savings - default_monthly_savings) > 1e-6
        allocated_monthly_savings, allocation_source = event_monthly_allocation(
            db, client_id, event, base_monthly_savings, evaluation_date, use_record=not what_if,
        )
    weight = PRIORITY_WEIGHTS.get(event.priority, 1)

    current_funded, weighted_return = calculate_current_funded_and_weighted_return(event, db)
    tax_rate = config.tax_rate if config else 20.0
    effective_return = blended_after_tax_return(
        db, client_id, gross_annual_return=base_annual_return, tax_rate=tax_rate,
    )
    years_remaining = max(0.0, (event.target_date - evaluation_date).days / 365.25)

    return {
        "current_funded": current_funded,
        "weighted_return": weighted_return,
        "annual_return": base_annual_return,
        "effective_return": effective_return,
        "contribution_annual_return": base_annual_return * (1 - tax_rate / 100.0),
        "tax_rate": tax_rate,
        "inflation_rate": base_inflation,
        "monthly_savings": base_monthly_savings,
        "allocated_monthly_savings": allocated_monthly_savings,
        "allocation_source": allocation_source,
        "contribution_schedule": contribution_schedule or [],
        "allocation_mode": allocation_mode,
        "priority_weight": weight,
        "years_remaining": years_remaining,
        "reference_date": evaluation_date,
    }


def run_monte_carlo(
    current_funded: float,
    monthly_savings: float,
    years_remaining: float,
    annual_return: float = 5.0,
    volatility: float = 15.0,
    inflation_rate: float = 2.0,
    n_simulations: int = 1000,
    *, contribution_annual_return: float | None = None,
) -> dict:
    """
    Monte Carlo simulation for goal projection.

    Draws from PROJECTION_SEED, so the same assumptions give the same answer and
    two scenarios differ only by the assumption that differs between them. An
    unseeded run made every comparison carry sampling noise of its own, and the
    same goal reported a different probability each time the page was opened.
    """
    if years_remaining <= 0:
        return {
            "simulated_end_values": [current_funded] * n_simulations,
            "percentiles": {"p10": current_funded, "p50": current_funded, "p90": current_funded},
            "year_by_year": {"p10": [], "p50": [], "p90": []},
        }

    r_mean = (annual_return - inflation_rate) / 100.0
    contribution_mean = ((annual_return if contribution_annual_return is None else contribution_annual_return) - inflation_rate) / 100.0
    r_std = max(volatility, 0.0) / 100.0
    full_years = int(years_remaining)
    partial_year = years_remaining - full_years
    n_years = full_years + (1 if partial_year > 0 else 0)

    all_year_balances = np.zeros((n_simulations, n_years + 1))
    all_year_balances[:, 0] = current_funded

    rng = np.random.default_rng(PROJECTION_SEED)
    annual_contribution = monthly_savings * 12
    held = np.full(n_simulations, current_funded, dtype=float)
    invested = np.zeros(n_simulations)
    for t in range(1, n_years + 1):
        shock = rng.normal(0, r_std, n_simulations)
        year_contribution = annual_contribution
        year_return_scale = 1.0
        if t == n_years and partial_year > 0:
            year_contribution = annual_contribution * partial_year
            year_return_scale = partial_year
        # One market shock moves both existing holdings and newly invested savings.
        held *= 1 + (r_mean + shock) * year_return_scale
        invested = (invested + year_contribution) * (1 + (contribution_mean + shock) * year_return_scale)
        all_year_balances[:, t] = held + invested

    end_values = all_year_balances[:, -1]
    p10, p50, p90 = np.percentile(end_values, [10, 50, 90])
    year_p10 = [float(np.percentile(all_year_balances[:, t], 10)) for t in range(n_years + 1)]
    year_p50 = [float(np.percentile(all_year_balances[:, t], 50)) for t in range(n_years + 1)]
    year_p90 = [float(np.percentile(all_year_balances[:, t], 90)) for t in range(n_years + 1)]

    return {
        "simulated_end_values": end_values.tolist(),
        "percentiles": {
            "p10": round(float(p10), 0),
            "p50": round(float(p50), 0),
            "p90": round(float(p90), 0),
        },
        "year_by_year": {
            "p10": [round(v, 0) for v in year_p10],
            "p50": [round(v, 0) for v in year_p50],
            "p90": [round(v, 0) for v in year_p90],
        },
    }


def calculate_goal_probability_monte_carlo(
    current_funded: float,
    monthly_savings: float,
    years_remaining: float,
    target_amount: float,
    annual_return: float = 5.0,
    volatility: float = 15.0,
    inflation_rate: float = 2.0,
    n_simulations: int = 1000,
    *, contribution_annual_return: float | None = None,
) -> float:
    """
    Estimate goal success probability (0.0-100.0) via Monte Carlo.
    """
    mc = run_monte_carlo(
        current_funded=current_funded,
        monthly_savings=monthly_savings,
        years_remaining=years_remaining,
        annual_return=annual_return,
        volatility=volatility,
        inflation_rate=inflation_rate,
        n_simulations=n_simulations,
        contribution_annual_return=contribution_annual_return,
    )
    end_values = mc["simulated_end_values"]
    if not end_values:
        return 0.0
    success_count = sum(1 for value in end_values if value >= target_amount)
    return round(success_count / len(end_values) * 100, 1)


def generate_roadmap(
    current_funded: float,
    monthly_savings: float,
    years_remaining: float,
    annual_return: float = 5.0,
    target_amount: float = 0.0,
    interval: str = 'auto',
    reference_date: Optional[date] = None,
    contribution_schedule: list[dict] | None = None,
    *, contribution_annual_return: float | None = None,
) -> List[dict]:
    """Generate time-period simulation data with configurable granularity.

    interval: 'auto' | 'monthly' | 'quarterly' | 'annual'
    Auto resolves to monthly (≤18 months), quarterly (≤60 months), or annual.

    When contribution_schedule is supplied the contribution column reflects the
    actual per-period cash (bonus in its exact month, one-time on its date, etc.).
    monthly_savings is still used as the fallback when no schedule is given.
    """
    ref_date = reference_date or date.today()
    r_annual = annual_return / 100.0
    contribution_rate = (annual_return if contribution_annual_return is None else contribution_annual_return) / 100.0
    months_remaining = max(1, round(years_remaining * 12))
    use_schedule = bool(contribution_schedule)

    if interval == 'auto':
        if months_remaining <= 18:
            effective = 'monthly'
        elif months_remaining <= 60:
            effective = 'quarterly'
        else:
            effective = 'annual'
    else:
        effective = interval

    def _row(period_idx: int, label: str, start_bal: float, contribution: float, gain: float, end_bal: float) -> dict:
        return {
            "year": period_idx,
            "label": label,
            "start_balance": round(start_bal, 2),
            "contribution": round(contribution, 2),
            "investment_gain": round(gain, 2),
            "end_balance": round(end_bal, 2),
            "goal_coverage": round((end_bal / target_amount * 100) if target_amount > 0 else 0, 1),
        }

    def _next_month_start(y: int, m: int) -> date:
        return date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)

    roadmap: List[dict] = []
    balance = current_funded
    held = current_funded
    invested = 0.0

    def advance(contribution: float, periods_per_year: int) -> float:
        nonlocal held, invested
        held *= (1 + r_annual) ** (1 / periods_per_year)
        invested = (invested + contribution) * (1 + contribution_rate) ** (1 / periods_per_year)
        return held + invested

    if effective == 'monthly':
        roadmap.append(_row(0, ref_date.strftime('%Y-%m'), balance, 0, 0, balance))
        for m in range(1, months_remaining + 1):
            raw_month = ref_date.month + m
            lbl_year = ref_date.year + (raw_month - 1) // 12
            lbl_month = ((raw_month - 1) % 12) + 1
            period_start = date(lbl_year, lbl_month, 1)
            period_end = _next_month_start(lbl_year, lbl_month)
            per_period = (
                _period_contribution_from_schedule(contribution_schedule, period_start, period_end)
                if use_schedule else monthly_savings
            )
            start_bal = balance
            end_bal = advance(per_period, 12)
            gain = end_bal - start_bal - per_period
            balance = end_bal
            roadmap.append(_row(m, f"{lbl_year:04d}-{lbl_month:02d}", start_bal, per_period, gain, end_bal))

    elif effective == 'quarterly':
        quarters_remaining = max(1, round(years_remaining * 4))
        start_q = (ref_date.month - 1) // 3 + 1
        roadmap.append(_row(0, f"{ref_date.year} Q{start_q}", balance, 0, 0, balance))
        for q in range(1, quarters_remaining + 1):
            raw_month = ref_date.month + q * 3
            lbl_year = ref_date.year + (raw_month - 1) // 12
            lbl_month = ((raw_month - 1) % 12) + 1
            lbl_q = (lbl_month - 1) // 3 + 1
            q_start_month = (lbl_q - 1) * 3 + 1
            period_start = date(lbl_year, q_start_month, 1)
            period_end = _next_month_start(lbl_year, min(q_start_month + 2, 12))
            if q_start_month + 3 > 12:
                period_end = date(lbl_year + 1, (q_start_month + 3) - 12, 1)
            per_period = (
                _period_contribution_from_schedule(contribution_schedule, period_start, period_end)
                if use_schedule else monthly_savings * 3
            )
            start_bal = balance
            end_bal = advance(per_period, 4)
            gain = end_bal - start_bal - per_period
            balance = end_bal
            roadmap.append(_row(q, f"{lbl_year} Q{lbl_q}", start_bal, per_period, gain, end_bal))

    else:  # annual
        roadmap.append(_row(0, "Current", balance, 0, 0, balance))
        for y in range(1, math.ceil(years_remaining) + 1):
            try:
                period_start = ref_date.replace(year=ref_date.year + y - 1)
            except ValueError:
                period_start = ref_date.replace(year=ref_date.year + y - 1, day=28)
            try:
                period_end = ref_date.replace(year=ref_date.year + y)
            except ValueError:
                period_end = ref_date.replace(year=ref_date.year + y, day=28)
            per_period = (
                _period_contribution_from_schedule(contribution_schedule, period_start, period_end)
                if use_schedule else monthly_savings * 12
            )
            start_bal = balance
            end_bal = advance(per_period, 1)
            gain = end_bal - start_bal - per_period
            balance = end_bal
            roadmap.append(_row(y, f"Year {y}", start_bal, per_period, gain, end_bal))

    return roadmap


def determine_status(projected: float, target: float, years_remaining: float) -> str:
    """Determine goal status based on projection vs target."""
    if years_remaining <= 0:
        if projected >= target:
            return "Achieved"
        return "Missed"
    
    ratio = projected / target if target > 0 else 0
    if ratio >= 1.0:
        return "On Track"
    elif ratio >= 0.7:
        return "At Risk"
    else:
        return "Off Track"


def _milestone_summary(milestone: models.Milestone | None, current_funded: float | None = None) -> dict | None:
    if milestone is None:
        return None
    data = {
        "id": milestone.id,
        "date": milestone.date.isoformat(),
        "target_amount": round(float(milestone.target_amount or 0.0), 2),
        "note": milestone.note,
        "source": milestone.source,
    }
    if current_funded is not None:
        data["gap"] = round(float(current_funded) - float(milestone.target_amount or 0.0), 2)
    return data


def calculate_milestone_plan_progress(
    event: models.LifeEvent,
    current_funded: float,
    evaluation_date: date,
) -> dict:
    """Compare actual funded amount against the adopted milestone plan.

    The expected amount is linearly interpolated between active milestones, using
    life_event.start_date (or created_at/today fallback) as the zero-balance plan
    start before the first milestone.
    """
    active_milestones = sorted(
        [m for m in (event.milestones or []) if getattr(m, "is_active_plan", True)],
        key=lambda m: (m.date, m.id),
    ) if event.direction != "income" else []
    if not active_milestones:
        return {
            "plan_expected_amount": 0.0,
            "plan_gap": 0.0,
            "plan_status": "No Plan" if event.direction == "income" else (event.plan_status_override or "No Plan"),
            "plan_progress_percentage": 0.0,
            "plan_previous_milestone": None,
            "plan_next_milestone": None,
        }

    previous_milestone = None
    next_milestone = None
    for milestone in active_milestones:
        if milestone.date <= evaluation_date:
            previous_milestone = milestone
        elif next_milestone is None:
            next_milestone = milestone
            break

    plan_start = event.start_date
    if plan_start is None and event.created_at is not None:
        plan_start = event.created_at.date()
    if plan_start is None:
        plan_start = min(evaluation_date, active_milestones[0].date)

    if next_milestone is None:
        expected = float(previous_milestone.target_amount or 0.0) if previous_milestone else 0.0
    elif previous_milestone is None:
        start_date = min(plan_start, next_milestone.date)
        start_amount = 0.0
        end_date = next_milestone.date
        end_amount = float(next_milestone.target_amount or 0.0)
        if evaluation_date <= start_date:
            expected = start_amount
        elif end_date <= start_date:
            expected = end_amount
        else:
            ratio = (evaluation_date - start_date).days / max((end_date - start_date).days, 1)
            expected = start_amount + (end_amount - start_amount) * max(0.0, min(1.0, ratio))
    else:
        start_date = previous_milestone.date
        start_amount = float(previous_milestone.target_amount or 0.0)
        end_date = next_milestone.date
        end_amount = float(next_milestone.target_amount or 0.0)
        if end_date <= start_date:
            expected = end_amount
        else:
            ratio = (evaluation_date - start_date).days / max((end_date - start_date).days, 1)
            expected = start_amount + (end_amount - start_amount) * max(0.0, min(1.0, ratio))

    gap = float(current_funded) - expected
    if event.plan_status_override:
        plan_status = event.plan_status_override
    elif expected <= 0:
        plan_status = "On Track"
    else:
        ratio = float(current_funded) / expected
        if ratio >= 1.05:
            plan_status = "Ahead"
        elif ratio >= 1.0:
            plan_status = "On Track"
        elif ratio >= 0.85:
            plan_status = "Watch"
        else:
            plan_status = "Behind"

    plan_progress = (float(current_funded) / expected * 100) if expected > 0 else 100.0
    return {
        "plan_expected_amount": round(expected, 2),
        "plan_gap": round(gap, 2),
        "plan_status": plan_status,
        "plan_progress_percentage": round(plan_progress, 1),
        "plan_previous_milestone": _milestone_summary(previous_milestone, current_funded),
        "plan_next_milestone": _milestone_summary(next_milestone, current_funded),
    }


def get_life_events_with_progress(
    db: Session,
    client_id: int,
    annual_return: float | None = None,
    monthly_savings: float | None = None,
    inflation: float | None = None,
    reference_date: Optional[date] = None,
    contribution_schedule: list[dict[str, Any]] | None = None,
    allocation_mode: str = "weighted",
    roadmap_interval: str = 'auto',
    include_archived: bool = False,
    scenario_id: int | None = None,
) -> List[dict]:
    """Get all life events with calculated progress for current client."""
    life_events = list_goals(db, client_id, include_archived=include_archived, scenario_id=scenario_id)
    
    evaluation_date = reference_date or date.today()
    result = []
    
    for event in life_events:
        # Keep receipts visible, but never describe them as underfunded goals.
        if event.direction == "income":
            result.append({
                **_income_event_with_progress(event, evaluation_date),
                **calculate_milestone_plan_progress(event, 0.0, evaluation_date),
            })
            continue
        context = get_goal_simulation_context(
            db=db,
            client_id=client_id,
            event=event,
            annual_return=annual_return,
            inflation=inflation,
            monthly_savings=monthly_savings,
            reference_date=evaluation_date,
            contribution_schedule=contribution_schedule,
            allocation_mode=allocation_mode,
        )
        current_funded = context["current_funded"]
        weighted_return = context["weighted_return"]
        effective_return = context["effective_return"]
        allocated_savings = context["allocated_monthly_savings"]
        years_remaining = context["years_remaining"]
        
        projected = calculate_projection(
            current_funded=current_funded,
            monthly_savings=allocated_savings,
            years_remaining=years_remaining,
            annual_return=effective_return,
            contribution_annual_return=context["contribution_annual_return"],
        )
        
        gap = event.target_amount - projected
        status = determine_status(projected, event.target_amount, years_remaining)
        progress_pct = (projected / event.target_amount * 100) if event.target_amount > 0 else 0
        funded_pct = (current_funded / event.target_amount * 100) if event.target_amount > 0 else 0
        plan_progress = calculate_milestone_plan_progress(event, current_funded, evaluation_date)
        
        # In direct mode pass the raw schedule so per-period contributions (bonus
        # month, one-time date) are shown accurately in the roadmap table.
        # In weighted mode the schedule amounts would need per-goal scaling, so
        # we fall back to the pre-averaged allocated_savings.
        raw_schedule = (
            context["contribution_schedule"]
            if context["allocation_mode"] == "direct" and context["contribution_schedule"]
            else None
        )
        roadmap = generate_roadmap(
            current_funded=current_funded,
            monthly_savings=allocated_savings,
            years_remaining=years_remaining,
            annual_return=effective_return,
            contribution_annual_return=context["contribution_annual_return"],
            target_amount=event.target_amount,
            interval=roadmap_interval,
            reference_date=evaluation_date,
            contribution_schedule=raw_schedule,
        )
        
        result.append({
            **_life_event_fields(event),
            "allocations": [],
            # The event's share of the monthly savings and where it comes from.
            "monthly_allocation": round(allocated_savings, 2),
            "allocation_source": context["allocation_source"],
            "current_funded": round(current_funded, 2),
            "projected_amount": round(projected, 2),
            "gap": round(gap, 2),
            "weighted_return": round(effective_return, 2),
            "gross_annual_return": context["annual_return"],
            "blended_after_tax_return": effective_return,
            "tax_rate": context["tax_rate"],
            "status": status,
            "progress_percentage": round(min(progress_pct, 100), 1),
            "funded_percentage": round(min(funded_pct, 100), 1),
            "years_remaining": round(years_remaining, 1),
            "roadmap": roadmap,
            **plan_progress,
        })
    
    return result


def _life_event_fields(event: models.LifeEvent) -> dict:
    return {
        "id": event.id,
        "scenario_id": event.scenario_id,
        "lineage": event.lineage,
        "name": event.name,
        "target_date": event.target_date.isoformat(),
        "target_amount": event.target_amount,
        "direction": event.direction,
        "account_id": event.account_id,
        "priority": event.priority,
        "note": event.note,
        "start_date": event.start_date.isoformat() if event.start_date else None,
        "condition_mode": event.condition_mode,
        "active_plan_basis": event.active_plan_basis,
        "active_plan_label": event.active_plan_label,
        "plan_status_override": event.plan_status_override,
        "budget_reflection": event.budget_reflection,
        "budget_reflection_effective": event.budget_reflection_effective,
        "archived_at": event.archived_at.isoformat() if event.archived_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _income_event_with_progress(event: models.LifeEvent, evaluation_date: date) -> dict:
    return {
        **_life_event_fields(event),
        "current_funded": 0.0,
        "projected_amount": 0.0,
        "gap": 0.0,
        "progress_percentage": 0.0,
        "funded_percentage": 0.0,
        "status": "Not Applicable",
        "years_remaining": round(max(0.0, (event.target_date - evaluation_date).days / 365.25), 1),
        "allocations": [],
        "roadmap": [],
    }


def calculate_overall_goal_probability(db: Session, client_id: int) -> dict:
    """Calculate overall probability of achieving all goals for current client."""
    events_with_progress = [event for event in get_life_events_with_progress(db, client_id=client_id)
                            if event.get("direction", "expense") == "expense"]
    
    if not events_with_progress:
        return {
            "overall_probability": 100,
            "total_goals": 0,
            "total_target": 0,
            "total_projected": 0,
            "goals": []
        }
    
    total_target = sum(e["target_amount"] for e in events_with_progress)
    total_projected = sum(e["projected_amount"] for e in events_with_progress)
    
    # Weighted average probability based on target amounts
    weighted_prob = sum(
        e["progress_percentage"] * (e["target_amount"] / total_target) 
        for e in events_with_progress
    ) if total_target > 0 else 0
    
    return {
        "overall_probability": round(min(weighted_prob, 100), 1),
        "total_goals": len(events_with_progress),
        "total_target": total_target,
        "total_projected": round(total_projected, 2),
        "goals": events_with_progress
    }


def calculate_roadmap_progression(events: list[dict]) -> dict:
    """Return weighted goal progression and status across all future liabilities."""
    events = [event for event in events if event.get("direction", "expense") == "expense"]
    total_target = sum((event.get("target_amount") or 0.0) for event in events)
    if not events or total_target <= 0:
        return {"progression": 100.0, "status": "On Track"}

    weighted_progress = sum(
        min(event.get("progress_percentage") or 0.0, 100.0)
        * ((event.get("target_amount") or 0.0) / total_target)
        for event in events
    )
    if weighted_progress >= 95:
        status = "On Track"
    elif weighted_progress >= 80:
        status = "At Risk"
    else:
        status = "Off Track"
    return {"progression": round(weighted_progress, 1), "status": status}


def simulate_net_worth_forward(
    db: Session,
    client_id: int,
    years: int = 30,
    annual_return: float = 5.0,
    inflation: float = 2.0,
    monthly_savings: float | None = None,
    contribution_schedule: list[dict[str, Any]] | None = None,
    *, include_event_income: bool = True,
    account_returns: dict[int, float] | None = None,
) -> list[dict]:
    """Simulate total net worth forward as yearly P10/P50/P90 bands."""
    projection, _ = simulate_net_worth_forward_with_paths(
        db, client_id, years, annual_return, inflation, monthly_savings,
        contribution_schedule, include_event_income=include_event_income,
        account_returns=account_returns,
    )
    return projection


def simulate_net_worth_forward_with_paths(
    db: Session,
    client_id: int,
    years: int = 30,
    annual_return: float = 5.0,
    inflation: float = 2.0,
    monthly_savings: float | None = None,
    contribution_schedule: list[dict[str, Any]] | None = None,
    *, include_event_income: bool = True,
    account_returns: dict[int, float] | None = None,
) -> tuple[list[dict], np.ndarray]:
    """Return bands and their paths x (years + 1) values from one seeded run."""

    years = max(1, min(years, 60))
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()
    if monthly_savings is None:
        monthly_savings = config.monthly_savings if config else 50000.0
    today = date.today()
    schedule_monthly = monthly_equivalent_from_contribution_schedule(
        contribution_schedule,
        today,
        today.replace(year=today.year + years),
    )
    if schedule_monthly is not None:
        monthly_savings = schedule_monthly
    volatility = config.volatility if config else 15.0

    bs = get_balance_sheet(db, client_id=client_id)
    starting_net_worth = bs.get("net_worth", 0.0) or 0.0
    annual_contribution = (monthly_savings or 0.0) * 12
    tax_rate = config.tax_rate if config else 20.0
    effective_return = blended_after_tax_return(
        db, client_id, gross_annual_return=annual_return, tax_rate=tax_rate,
        account_returns=account_returns,
    )
    blended_real = (effective_return - inflation) / 100.0
    contribution_real = (annual_return * (1 - tax_rate / 100.0) - inflation) / 100.0
    return_std = max(volatility or 0.0, 0.0) / 100.0
    current_year = today.year

    n_simulations = 1200
    rng = np.random.default_rng(PROJECTION_SEED)
    # 年利 describes how new savings will be invested; existing holdings
    # already have their own account rates, including cash held at zero percent.
    earning = np.full(n_simulations, positive_asset_balance(db, client_id), dtype=float)
    # Loans, overdrafts and other net-worth residuals are not invested. Keep
    # their nominal principal flat, using the projection's real-rate convention.
    residual = starting_net_worth - earning[0]
    invested = np.zeros(n_simulations)
    paths = np.empty((n_simulations, years + 1))
    paths[:, 0] = starting_net_worth
    projection = [
        {
            "year": current_year,
            "p10": round(float(starting_net_worth), 0),
            "p50": round(float(starting_net_worth), 0),
            "p90": round(float(starting_net_worth), 0),
        }
    ]

    for offset in range(1, years + 1):
        shock = rng.normal(0, return_std, n_simulations)
        earning *= 1 + blended_real + shock
        residual *= 1 - inflation / 100.0
        invested = (invested + annual_contribution) * (1 + contribution_real + shock)
        paths[:, offset] = earning + residual + invested
        p10, p50, p90 = np.percentile(paths[:, offset], [10, 50, 90])
        projection.append(
            {
                "year": current_year + offset,
                "p10": round(float(p10), 0),
                "p50": round(float(p50), 0),
                "p90": round(float(p90), 0),
            }
        )

    if include_event_income:
        # Scenario walks supply resolved dates themselves, so they opt out of stored dates.
        demand = aggregate_life_event_demand_by_year(db, client_id, years)
        paths += np.array([due["cumulative_income"] for due in demand])
        projection = [{**row, "cumulative_income": due["cumulative_income"],
                       **{band: row[band] + due["cumulative_income"] for band in ("p10", "p50", "p90")}}
                      for row, due in zip(projection, demand)]
    return projection, paths


def aggregate_life_event_demand_by_year(
    db: Session,
    client_id: int,
    years: int = 30,
) -> list[dict]:
    """Return cumulative future liability demand by calendar year."""
    years = max(1, min(years, 60))
    life_events = goal_events_query(db, client_id).order_by(models.LifeEvent.target_date, models.LifeEvent.id).all()

    return aggregate_event_demand_by_year(
        [(event.target_date, event.target_amount or 0.0) for event in life_events if event.direction == "expense"], years,
        income_events=[(event.target_date, event.target_amount or 0.0) for event in life_events if event.direction == "income"],
    )


def aggregate_event_demand_by_year(
    events: list[tuple[date | None, float]], years: int = 30,
    *, income_events: list[tuple[date | None, float]] | None = None,
) -> list[dict]:
    """Share calendar-year demand math between stored goals and resolved scenarios."""
    years = max(1, min(years, 60))
    current_year = date.today().year
    rows = []
    for year in range(current_year, current_year + years + 1):
        due = [amount for target_date, amount in events if target_date and target_date.year <= year]
        rows.append({
            "year": year,
            "cumulative_target": round(sum(due), 0),
            "cumulative_income": round(sum(amount for target_date, amount in (income_events or []) if target_date and target_date.year <= year), 0),
            "event_count": len(due),
        })
    return rows


def get_roadmap_projection(
    db: Session,
    client_id: int,
    years: int = 30,
    annual_return: float = 5.0,
    inflation: float = 2.0,
    monthly_savings: float | None = None,
    contribution_schedule: list[dict[str, Any]] | None = None,
    allocation_mode: str = "weighted",
    roadmap_interval: str = "auto",
    include_archived: bool = False,
) -> dict:
    """Combine historical net worth, forward simulation, goals, and milestones."""

    events = get_life_events_with_progress(
        db=db,
        client_id=client_id,
        annual_return=annual_return,
        monthly_savings=monthly_savings if monthly_savings is not None else 50000.0,
        inflation=inflation,
        contribution_schedule=contribution_schedule,
        allocation_mode=allocation_mode,
        roadmap_interval=roadmap_interval,
        include_archived=include_archived,
    )
    progression = calculate_roadmap_progression([event for event in events if not event["archived_at"]])
    milestones = db.query(models.Milestone).filter(
        models.Milestone.client_id == client_id,
        # Standalone milestones remain visible; copied event milestones belong to their story.
        (models.Milestone.life_event_id.is_(None)) | models.Milestone.life_event_id.in_([event["id"] for event in events]),
    ).order_by(models.Milestone.date, models.Milestone.id).all()
    event_name_by_id = {event["id"]: event["name"] for event in events}
    demand = aggregate_life_event_demand_by_year(db, client_id, years)
    # This chart presents liabilities separately; the forward simulation includes receipts.
    projection = simulate_net_worth_forward(
        db=db, client_id=client_id, years=years, annual_return=annual_return,
        inflation=inflation, monthly_savings=monthly_savings,
        contribution_schedule=contribution_schedule,
    )

    return {
        "history": get_net_worth_history(db, client_id=client_id, months=24),
        "projection": projection,
        "liability_demand": demand,
        "milestones": [
            {
                "id": milestone.id,
                "life_event_id": milestone.life_event_id,
                "life_event_name": event_name_by_id.get(milestone.life_event_id),
                "date": milestone.date.isoformat(),
                "target_amount": milestone.target_amount,
                "note": milestone.note,
                "source": milestone.source,
                "is_active_plan": milestone.is_active_plan,
            }
            for milestone in milestones
        ],
        "events": events,
        "roadmap_progression": progression["status"],
        "roadmap_progression_pct": progression["progression"],
        "params": {
            "years": years,
            "annual_return": annual_return,
            "inflation": inflation,
            "monthly_savings": monthly_savings,
            "contribution_schedule": contribution_schedule or [],
            "reference_date": date.today().isoformat(),
        },
    }


def get_strategy_dashboard(
    db: Session,
    client_id: int,
    annual_return: float | None = 5.0,
    inflation: float | None = 2.0,
    monthly_savings: float | None = 50000.0,
    contribution_schedule: list[dict[str, Any]] | None = None,
    allocation_mode: str = "weighted",
    roadmap_interval: str = 'auto',
) -> dict:
    """Get comprehensive strategy dashboard with events and unallocated assets."""

    events = get_life_events_with_progress(
        db,
        client_id,
        annual_return=annual_return,
        monthly_savings=monthly_savings,
        inflation=inflation,
        contribution_schedule=contribution_schedule,
        allocation_mode=allocation_mode,
        roadmap_interval=roadmap_interval,
    )
    
    return {
        "events": events,
        "unallocated_assets": [],
        "total_allocated": 0.0,
        "total_unallocated": 0.0,
        "simulation_params": {
            "annual_return": annual_return,
            "inflation": inflation,
            "monthly_savings": monthly_savings,
            "contribution_schedule": contribution_schedule or [],
            "allocation_mode": allocation_mode,
        }
    }


def summarize_goal_funding_gap(db: Session, client_id: int) -> dict:
    """Goal-side inputs for the budget summary.

    Lives here rather than in budget_plan_service so that planning never has to
    import the goal domain; the caller composes the two.
    """
    events = [event for event in get_life_events_with_progress(db, client_id=client_id)
              if event.get("direction", "expense") == "expense"]
    total_gap = sum(max(0, e["gap"]) for e in events)
    avg_years = (
        sum(e["years_remaining"] for e in events) / len(events)
        if events else 10
    )
    return {
        "goals_count": len(events),
        "total_goal_gap": total_gap,
        "required_monthly_savings": total_gap / (avg_years * 12) if avg_years > 0 else 0,
    }
