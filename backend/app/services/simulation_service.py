"""Simulation service boundary.

Simulation depends on goal funding math, but callers should not need to import the broad
strategy service just to run projections or Monte Carlo analysis.
"""

from .strategy_service import (
    calculate_current_funded_and_weighted_return,
    calculate_goal_probability_monte_carlo,
    calculate_projection,
    run_monte_carlo,
)

__all__ = [
    "calculate_current_funded_and_weighted_return",
    "calculate_goal_probability_monte_carlo",
    "calculate_projection",
    "run_monte_carlo",
]
