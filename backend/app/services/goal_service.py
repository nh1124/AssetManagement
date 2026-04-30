"""Goal service boundary.

The public API still exposes legacy /life-events routes, but UI responsibility now treats
these records as the Goal domain. This module keeps routers and reports from depending on
strategy execution services directly.
"""

from .strategy_service import (
    calculate_overall_goal_probability,
    generate_budget_from_goals,
    get_life_events_with_progress,
    get_strategy_dashboard,
)

__all__ = [
    "calculate_overall_goal_probability",
    "generate_budget_from_goals",
    "get_life_events_with_progress",
    "get_strategy_dashboard",
]
