"""What the goal scenario asks of the monthly budget, read without writing.

Planning never imports the goal domain; the goal-budget workflow composes this
reading with the budget store. Each goal event is classified once here, by its
budget reflection (確定 / 条件つき / 試算のみ), and given the monthly amount that
would fund it from the first reflected month.

Near events are funded in cash (a capsule earns nothing in this plan), so their
monthly amount is the shortfall over the remaining months. Far events are part
of the invested savings, so their amount assumes the scenario's after-tax return
on both the money already held and every new contribution.
"""
from __future__ import annotations

from decimal import ROUND_CEILING

from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from .goal_service import goal_events_query
from .life_event_conditions import evaluate_all
from .life_scenario_scope import get_goal
from .life_scenario_service import monthly_savings
from .money_storage import money_client_currency
from .strategy_service import calculate_current_funded_and_weighted_return


def months_until(start_period: str, target) -> int:
    """Monthly contributions from the start month up to, not including, the target month."""
    year, month = (int(part) for part in start_period.split("-"))
    return (target.year - year) * 12 + (target.month - month)


def _monthly_minor(need: float, months: int, monthly_rate: float, currency: str) -> int:
    if need <= 0:
        return 0
    if monthly_rate <= 0:
        amount = need / months
    else:
        amount = need * monthly_rate / ((1 + monthly_rate) ** months - 1)
    # Round up: a required amount rounded down would leave the goal short. The
    # float is trimmed first so representation noise cannot add a whole unit.
    return Money.from_float(float(round(amount, 6)), currency, rounding=ROUND_CEILING).minor


def _status(event: models.LifeEvent, reflection: str, judged: dict, months: int) -> str:
    if event.direction == "income":
        return "income"
    if reflection == "simulation_only":
        return "simulation_only"
    if reflection == "conditional" and judged.get("conditions"):
        satisfied = judged.get("satisfied")
        if satisfied is None:
            return "condition_unknown"
        if satisfied is False:
            return "condition_unmet"
    if months < 0:
        return "past_due"
    return "reflected"


def goal_budget_inputs(db: Session, client_id: int, *, start_period: str, near_years: int | None) -> dict:
    goal = get_goal(db, client_id)
    if goal is None:
        return {"scenario": None, "events": []}
    currency = money_client_currency(db, client_id)
    config = db.query(models.SimulationConfig).filter_by(client_id=client_id).first()
    tax_rate = config.tax_rate if config and config.tax_rate is not None else 20.0
    after_tax_return = goal.annual_return * (1 - tax_rate / 100)
    monthly_rate = (1 + after_tax_return / 100) ** (1 / 12) - 1 if after_tax_return > -100 else 0.0
    judged = evaluate_all(db, client_id)
    rows = []
    for event in goal_events_query(db, client_id).order_by(models.LifeEvent.target_date, models.LifeEvent.id).all():
        months = months_until(start_period, event.target_date)
        reflection = event.budget_reflection_effective
        conditions = judged.get(event.id, {}).get("conditions", [])
        status = _status(event, reflection, judged.get(event.id, {}), months)
        near = near_years is None or months < near_years * 12
        funded = calculate_current_funded_and_weighted_return(event, db)[0] if event.direction == "expense" else 0.0
        target = event.target_amount or 0.0
        contributions = max(1, months)
        if event.direction != "expense" or status == "past_due":
            required_minor = 0
        elif near:
            required_minor = _monthly_minor(target - funded, contributions, 0.0, currency)
        else:
            grown = funded * (1 + monthly_rate) ** contributions if monthly_rate > 0 else funded
            required_minor = _monthly_minor(target - grown, contributions, monthly_rate, currency)
        capsule = next(iter(sorted(event.capsules, key=lambda row: row.id)), None)
        rows.append({
            "event_id": event.id,
            "name": event.name,
            "direction": event.direction,
            "target_date": event.target_date.isoformat(),
            "target_amount": target,
            "funded": funded,
            "reflection": reflection,
            "reflection_chosen": event.budget_reflection is not None,
            "status": status,
            "near": near,
            "months": months,
            "monthly_required_minor": required_minor,
            "capsule_id": capsule.id if capsule else None,
            "capsule_name": capsule.name if capsule else None,
            "conditions_total": len(conditions),
            "conditions_met": sum(1 for row in conditions if row.get("satisfied") is True),
        })
    return {
        "scenario": {
            "id": goal.id,
            "name": goal.name,
            "monthly_savings": monthly_savings(db, goal),
            "monthly_savings_is_default": goal.monthly_savings_minor is None,
            "annual_return": goal.annual_return,
            "after_tax_return": after_tax_return,
        },
        "events": rows,
    }
