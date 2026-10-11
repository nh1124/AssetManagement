from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..services.goal_service import get_life_event
from ..services.simulation_config_service import get_config
from ..services.simulation_service import (
    calculate_goal_probability_monte_carlo,
    get_goal_simulation_context,
    run_monte_carlo,
)


def _parse_contribution_schedule(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid contribution_schedule JSON") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="contribution_schedule must be a list")
    return [item for item in value if isinstance(item, dict)]


def monte_carlo_for_goal(
    db: Session, client_id: int, life_event_id: int, *,
    n_simulations: int,
    annual_return: float | None,
    inflation: float | None,
    monthly_savings: float | None,
    contribution_schedule: str | None,
    allocation_mode: str,
) -> dict:
    event = get_life_event(db, client_id, life_event_id)
    # These raises are ordered deliberately: a malformed schedule on a missing
    # event has always returned 404, and callers may rely on that precedence.
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")

    config = get_config(db, client_id)
    volatility = config.volatility if config else 15.0
    context = get_goal_simulation_context(
        db,
        client_id,
        event,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=_parse_contribution_schedule(contribution_schedule),
        allocation_mode=allocation_mode,
    )

    mc_result = run_monte_carlo(
        current_funded=context["current_funded"],
        monthly_savings=context["allocated_monthly_savings"],
        years_remaining=context["years_remaining"],
        annual_return=context["effective_return"],
        volatility=volatility,
        inflation_rate=context["inflation_rate"],
        n_simulations=n_simulations,
    )
    probability = calculate_goal_probability_monte_carlo(
        current_funded=context["current_funded"],
        monthly_savings=context["allocated_monthly_savings"],
        years_remaining=context["years_remaining"],
        target_amount=event.target_amount,
        annual_return=context["effective_return"],
        volatility=volatility,
        inflation_rate=context["inflation_rate"],
        n_simulations=n_simulations,
    )

    return {
        "life_event_id": life_event_id,
        "life_event_name": event.name,
        "target_amount": event.target_amount,
        "years_remaining": round(context["years_remaining"], 1),
        "probability": probability,
        "percentiles": mc_result["percentiles"],
        "year_by_year": mc_result["year_by_year"],
        "n_simulations": n_simulations,
    }
