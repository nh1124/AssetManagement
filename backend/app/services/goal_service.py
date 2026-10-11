"""Goal service boundary.

The public API still exposes legacy /life-events routes, but UI responsibility now treats
these records as the Goal domain. This module keeps routers and reports from depending on
strategy execution services directly.
"""

from sqlalchemy.orm import Session

from .. import models
from .strategy_service import (
    calculate_overall_goal_probability,
    generate_budget_from_goals,
    get_life_events_with_progress,
    get_strategy_dashboard,
    summarize_goal_funding_gap,
)

__all__ = [
    "calculate_overall_goal_probability",
    "generate_budget_from_goals",
    "get_life_events_with_progress",
    "get_life_event",
    "get_strategy_dashboard",
    "summarize_goal_funding_gap",
]


def get_life_event(db: Session, client_id: int, life_event_id: int) -> models.LifeEvent | None:
    return db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == client_id,
    ).first()
