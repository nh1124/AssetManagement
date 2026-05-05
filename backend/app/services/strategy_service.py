"""Shared goal calculation primitives.

This module is retained as the implementation home for projection math during the
transition from the old all-in-one Strategy workspace. Domain callers should prefer
goal_service or simulation_service so UI responsibilities stay decoupled.
"""
from __future__ import annotations

from sqlalchemy.orm import Session
from datetime import date
from typing import Any, List, Optional, Tuple
import numpy as np
from .. import models
from .fx_service import calculate_account_valued_balance


def calculate_current_funded_and_weighted_return(event: models.LifeEvent, db: Optional[Session] = None) -> Tuple[float, float]:
    """Calculate current funded amount and weighted average return from CapsuleHoldings."""
    capsule = next((c for c in (event.capsules or [])), None)
    if not capsule or not capsule.holdings:
        return 0.0, 5.0

    total_funded = 0.0
    weighted_return_sum = 0.0

    for h in capsule.holdings:
        held = h.held_amount or 0.0
        if held > 0:
            total_funded += held
            account_return = (h.account.expected_return or 0.0) if h.account else 0.0
            weighted_return_sum += held * account_return

    weighted_return = weighted_return_sum / total_funded if total_funded > 0 else 5.0
    return total_funded, weighted_return


def calculate_current_funded(event: models.LifeEvent) -> float:
    total, _ = calculate_current_funded_and_weighted_return(event)
    return total



def calculate_projection(
    current_funded: float,
    monthly_savings: float,
    years_remaining: float,
    annual_return: float = 5.0
) -> float:
    """
    Calculate projected future value using the loop-based 'Roadmap' logic.
    Year End Balance = (Start Balance + Annual Contribution) * (1 + Annual Return Rate)
    """
    if years_remaining <= 0:
        return current_funded
    
    r = annual_return / 100.0
    balance = current_funded
    annual_contribution = monthly_savings * 12
    
    full_years = int(years_remaining)
    partial_year = years_remaining - full_years
    
    # Loop through full years
    for _ in range(full_years):
        balance = (balance + annual_contribution) * (1 + r)
        
    # Add partial year if any
    if partial_year > 0:
        balance = (balance + annual_contribution * partial_year) * (1 + r * partial_year)
        
    return balance


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

    base_monthly_savings = monthly_savings
    if base_monthly_savings is None:
        base_monthly_savings = config.monthly_savings if config else 50000.0

    evaluation_date = reference_date or date.today()
    schedule_monthly = monthly_equivalent_from_contribution_schedule(
        contribution_schedule,
        evaluation_date,
        event.target_date,
    )
    if schedule_monthly is not None:
        base_monthly_savings = schedule_monthly

    life_events = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id
    ).all()
    priority_weight_map = {1: 3, 2: 2, 3: 1}
    total_weight = sum(priority_weight_map.get(item.priority, 1) for item in life_events) or 1
    weight = priority_weight_map.get(event.priority, 1)
    allocation_ratio = weight / total_weight if allocation_mode != "direct" else 1.0

    current_funded, weighted_return = calculate_current_funded_and_weighted_return(event, db)
    has_holdings = any(c.holdings for c in event.capsules)
    effective_return = weighted_return if has_holdings else base_annual_return
    years_remaining = max(0.0, (event.target_date - evaluation_date).days / 365.25)

    return {
        "current_funded": current_funded,
        "weighted_return": weighted_return,
        "annual_return": base_annual_return,
        "effective_return": effective_return,
        "inflation_rate": base_inflation,
        "monthly_savings": base_monthly_savings,
        "allocated_monthly_savings": base_monthly_savings * allocation_ratio,
        "contribution_schedule": contribution_schedule or [],
        "allocation_mode": allocation_mode,
        "priority_weight": weight,
        "total_priority_weight": total_weight,
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
) -> dict:
    """
    Monte Carlo simulation for goal projection.
    """
    if years_remaining <= 0:
        return {
            "simulated_end_values": [current_funded] * n_simulations,
            "percentiles": {"p10": current_funded, "p50": current_funded, "p90": current_funded},
            "year_by_year": {"p10": [], "p50": [], "p90": []},
        }

    r_mean = (annual_return - inflation_rate) / 100.0
    r_std = max(volatility, 0.0) / 100.0
    full_years = int(years_remaining)
    partial_year = years_remaining - full_years
    n_years = full_years + (1 if partial_year > 0 else 0)

    all_year_balances = np.zeros((n_simulations, n_years + 1))
    all_year_balances[:, 0] = current_funded

    annual_contribution = monthly_savings * 12
    for t in range(1, n_years + 1):
        returns = np.random.normal(r_mean, r_std, n_simulations)
        year_contribution = annual_contribution
        year_return_scale = 1.0
        if t == n_years and partial_year > 0:
            year_contribution = annual_contribution * partial_year
            year_return_scale = partial_year
        all_year_balances[:, t] = (
            all_year_balances[:, t - 1] + year_contribution
        ) * (1 + returns * year_return_scale)

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
) -> List[dict]:
    """Generate time-period simulation data with configurable granularity.

    interval: 'auto' | 'monthly' | 'quarterly' | 'annual'
    Auto resolves to monthly (≤18 months), quarterly (≤60 months), or annual.
    """
    ref_date = reference_date or date.today()
    r_annual = annual_return / 100.0
    months_remaining = max(1, round(years_remaining * 12))

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

    roadmap: List[dict] = []
    balance = current_funded

    if effective == 'monthly':
        r_period = (1 + r_annual) ** (1 / 12) - 1
        per_period = monthly_savings
        roadmap.append(_row(0, ref_date.strftime('%Y-%m'), balance, 0, 0, balance))
        for m in range(1, months_remaining + 1):
            start_bal = balance
            end_bal = (start_bal + per_period) * (1 + r_period)
            gain = end_bal - start_bal - per_period
            balance = end_bal
            raw_month = ref_date.month + m
            lbl_year = ref_date.year + (raw_month - 1) // 12
            lbl_month = ((raw_month - 1) % 12) + 1
            roadmap.append(_row(m, f"{lbl_year:04d}-{lbl_month:02d}", start_bal, per_period, gain, end_bal))

    elif effective == 'quarterly':
        r_period = (1 + r_annual) ** (1 / 4) - 1
        per_period = monthly_savings * 3
        quarters_remaining = max(1, round(years_remaining * 4))
        start_q = (ref_date.month - 1) // 3 + 1
        roadmap.append(_row(0, f"{ref_date.year} Q{start_q}", balance, 0, 0, balance))
        for q in range(1, quarters_remaining + 1):
            start_bal = balance
            end_bal = (start_bal + per_period) * (1 + r_period)
            gain = end_bal - start_bal - per_period
            balance = end_bal
            raw_month = ref_date.month + q * 3
            lbl_year = ref_date.year + (raw_month - 1) // 12
            lbl_month = ((raw_month - 1) % 12) + 1
            lbl_q = (lbl_month - 1) // 3 + 1
            roadmap.append(_row(q, f"{lbl_year} Q{lbl_q}", start_bal, per_period, gain, end_bal))

    else:  # annual
        per_period = monthly_savings * 12
        roadmap.append(_row(0, "Current", balance, 0, 0, balance))
        for y in range(1, int(years_remaining) + 1):
            start_bal = balance
            end_bal = (start_bal + per_period) * (1 + r_annual)
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
) -> List[dict]:
    """Get all life events with calculated progress for current client."""
    life_events = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id
    ).all()
    
    evaluation_date = reference_date or date.today()
    result = []
    
    for event in life_events:
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
            annual_return=effective_return
        )
        
        gap = event.target_amount - projected
        status = determine_status(projected, event.target_amount, years_remaining)
        progress_pct = (projected / event.target_amount * 100) if event.target_amount > 0 else 0
        
        # Generate roadmap
        roadmap = generate_roadmap(
            current_funded=current_funded,
            monthly_savings=allocated_savings,
            years_remaining=years_remaining,
            annual_return=effective_return,
            target_amount=event.target_amount,
            interval=roadmap_interval,
            reference_date=evaluation_date,
        )
        
        result.append({
            "id": event.id,
            "name": event.name,
            "target_date": event.target_date.isoformat(),
            "target_amount": event.target_amount,
            "priority": event.priority,
            "note": event.note,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "allocations": [],
            "current_funded": round(current_funded, 2),
            "projected_amount": round(projected, 2),
            "gap": round(gap, 2),
            "weighted_return": round(effective_return, 2),
            "status": status,
            "progress_percentage": round(min(progress_pct, 100), 1),
            "years_remaining": round(years_remaining, 1),
            "roadmap": roadmap
        })
    
    return result


def calculate_overall_goal_probability(db: Session, client_id: int) -> dict:
    """Calculate overall probability of achieving all goals for current client."""
    events_with_progress = get_life_events_with_progress(db, client_id=client_id)
    
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
) -> list[dict]:
    """Simulate total net worth forward as yearly P10/P50/P90 bands."""
    from .accounting_service import get_balance_sheet

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
    real_return = (annual_return - inflation) / 100.0
    return_std = max(volatility or 0.0, 0.0) / 100.0
    current_year = today.year

    n_simulations = 1200
    rng = np.random.default_rng(42)
    balances = np.full(n_simulations, starting_net_worth, dtype=float)
    projection = [
        {
            "year": current_year,
            "p10": round(float(starting_net_worth), 0),
            "p50": round(float(starting_net_worth), 0),
            "p90": round(float(starting_net_worth), 0),
        }
    ]

    for offset in range(1, years + 1):
        sampled_returns = rng.normal(real_return, return_std, n_simulations)
        balances = (balances + annual_contribution) * (1 + sampled_returns)
        p10, p50, p90 = np.percentile(balances, [10, 50, 90])
        projection.append(
            {
                "year": current_year + offset,
                "p10": round(float(p10), 0),
                "p50": round(float(p50), 0),
                "p90": round(float(p90), 0),
            }
        )

    return projection


def aggregate_life_event_demand_by_year(
    db: Session,
    client_id: int,
    years: int = 30,
) -> list[dict]:
    """Return cumulative future liability demand by calendar year."""
    years = max(1, min(years, 60))
    current_year = date.today().year
    life_events = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id
    ).order_by(models.LifeEvent.target_date, models.LifeEvent.id).all()

    rows = []
    for year in range(current_year, current_year + years + 1):
        due = [
            event for event in life_events
            if event.target_date and event.target_date.year <= year
        ]
        rows.append(
            {
                "year": year,
                "cumulative_target": round(
                    sum((event.target_amount or 0.0) for event in due),
                    0,
                ),
                "event_count": len(due),
            }
        )
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
) -> dict:
    """Combine historical net worth, forward simulation, goals, and milestones."""
    from .analysis_service import get_net_worth_history

    events = get_life_events_with_progress(
        db=db,
        client_id=client_id,
        annual_return=annual_return,
        monthly_savings=monthly_savings if monthly_savings is not None else 50000.0,
        inflation=inflation,
        contribution_schedule=contribution_schedule,
        allocation_mode=allocation_mode,
    )
    progression = calculate_roadmap_progression(events)
    milestones = db.query(models.Milestone).filter(
        models.Milestone.client_id == client_id
    ).order_by(models.Milestone.date, models.Milestone.id).all()
    event_name_by_id = {event["id"]: event["name"] for event in events}

    return {
        "history": get_net_worth_history(db, client_id=client_id, months=24),
        "projection": simulate_net_worth_forward(
            db=db,
            client_id=client_id,
            years=years,
            annual_return=annual_return,
            inflation=inflation,
            monthly_savings=monthly_savings,
            contribution_schedule=contribution_schedule,
        ),
        "liability_demand": aggregate_life_event_demand_by_year(
            db=db,
            client_id=client_id,
            years=years,
        ),
        "milestones": [
            {
                "id": milestone.id,
                "life_event_id": milestone.life_event_id,
                "life_event_name": event_name_by_id.get(milestone.life_event_id),
                "date": milestone.date.isoformat(),
                "target_amount": milestone.target_amount,
                "note": milestone.note,
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


def generate_budget_from_goals(db: Session, month: str, client_id: int) -> List[dict]:
    """Generate a budget template derived from life event goals for current client."""
    life_events = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id
    ).all()
    
    # Get simulation config for monthly savings
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()
    total_monthly_savings = config.monthly_savings if config else 100000
    
    budget_items = []
    
    # Allocate savings across goals based on priority
    priority_weights = {1: 3, 2: 2, 3: 1}
    total_weight = sum(priority_weights.get(e.priority, 1) for e in life_events) or 1
    
    for event in life_events:
        weight = priority_weights.get(event.priority, 1)
        allocation = (weight / total_weight) * total_monthly_savings
        
        budget_items.append({
            "category": f"Savings: {event.name}",
            "proposed_amount": allocation,
            "derived_from": event.name,
            "month": month
        })
    
    return budget_items
