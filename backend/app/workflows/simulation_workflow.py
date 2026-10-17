from __future__ import annotations


from ..domain.errors import NotFound, Refused
from ..utils.contribution_schedule import parse_contribution_schedule
from sqlalchemy.orm import Session

from ..services.goal_service import get_life_event
from ..services.simulation_config_service import get_config
from ..services.simulation_service import (
    calculate_goal_probability_monte_carlo,
    get_goal_simulation_context,
    run_monte_carlo,
)


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
        raise NotFound("Life event not found")
    if event.direction == "income":
        raise Refused("収入イベントには積立達成率を計算できません。", status_code=422)

    config = get_config(db, client_id)
    volatility = config.volatility if config else 15.0
    context = get_goal_simulation_context(
        db,
        client_id,
        event,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=parse_contribution_schedule(contribution_schedule),
        allocation_mode=allocation_mode,
    )

    mc_result = run_monte_carlo(
        current_funded=context["current_funded"],
        monthly_savings=context["allocated_monthly_savings"],
        years_remaining=context["years_remaining"],
        annual_return=context["effective_return"],
        contribution_annual_return=context["contribution_annual_return"],
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
        contribution_annual_return=context["contribution_annual_return"],
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
