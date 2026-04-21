from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from .analysis_service import get_summary
from .strategy_service import (
    calculate_current_funded_and_weighted_return,
    calculate_goal_probability_monte_carlo,
)

ANNUAL_RETURN_DEFAULT = 5.0
YEARS_FOR_OPPORTUNITY_COST = 30


def audit_purchase(
    db: Session,
    client_id: int,
    price: float,
    lifespan_months: int,
    name: str = "",
) -> dict:
    daily_cost = price / (lifespan_months * 30)
    monthly_cost = price / lifespan_months

    r = ANNUAL_RETURN_DEFAULT / 100.0
    opportunity_value = price * ((1 + r) ** YEARS_FOR_OPPORTUNITY_COST)

    summary = get_summary(db, client_id)
    logical_balance_after = (summary.get("effective_cash") or 0) - price

    life_events = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id
    ).all()
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()

    annual_return = config.annual_return if config else 5.0
    volatility = getattr(config, "volatility", 15.0)
    inflation = getattr(config, "inflation_rate", 2.0)
    monthly_savings = config.monthly_savings if config else 50000.0

    priority_weight = {1: 3, 2: 2, 3: 1}
    total_weight = sum(priority_weight.get(e.priority, 1) for e in life_events) or 1

    today = date.today()
    goal_impacts = []
    max_delta = 0.0

    for event in life_events:
        years_remaining = max(0.0, (event.target_date - today).days / 365.25)
        current_funded, weighted_return = calculate_current_funded_and_weighted_return(event)
        effective_return = weighted_return if event.allocations else annual_return
        weight = priority_weight.get(event.priority, 1)
        alloc_savings = monthly_savings * (weight / total_weight)

        prob_before = calculate_goal_probability_monte_carlo(
            current_funded,
            alloc_savings,
            years_remaining,
            event.target_amount,
            effective_return,
            volatility,
            inflation,
        )

        funded_after = max(0.0, current_funded - price)
        prob_after = calculate_goal_probability_monte_carlo(
            funded_after,
            alloc_savings,
            years_remaining,
            event.target_amount,
            effective_return,
            volatility,
            inflation,
        )

        delta = prob_after - prob_before
        goal_impacts.append(
            {
                "life_event_name": event.name,
                "current_probability": round(prob_before, 1),
                "new_probability": round(prob_after, 1),
                "delta": round(delta, 1),
            }
        )
        max_delta = min(max_delta, delta)

    goal_impacts.sort(key=lambda x: x["delta"])

    asset_recognition = price >= 30000 and lifespan_months >= 12
    if logical_balance_after < 0:
        verdict = "Stop"
        reason = f"Effective cash turns negative after purchase (¥{logical_balance_after:,.0f})."
    elif max_delta < -10:
        verdict = "Stop"
        reason = f"Top goal probability drops by {abs(max_delta):.1f}%."
    elif max_delta < -5 or logical_balance_after < 50000:
        verdict = "Wait"
        reason = "Goal probability or short-term liquidity would be meaningfully weakened."
    else:
        verdict = "Go"
        reason = "Financial impact is acceptable."

    return {
        "tco_analysis": {
            "daily_cost": round(daily_cost, 0),
            "monthly_cost": round(monthly_cost, 0),
            "total_cost": price,
        },
        "opportunity_cost": {
            "invested_30y_value": round(opportunity_value, 0),
            "description": (
                f"Future value if invested at {ANNUAL_RETURN_DEFAULT}% for {YEARS_FOR_OPPORTUNITY_COST} years."
            ),
        },
        "goal_impact": goal_impacts,
        "logical_balance_after": round(logical_balance_after, 0),
        "verdict": verdict,
        "verdict_reason": reason,
        "asset_recognition": asset_recognition,
    }
