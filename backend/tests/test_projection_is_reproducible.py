"""Projections must not move when nothing about the plan moved.

run_monte_carlo drew from numpy global state with no seed, so the same goal
reported a different probability each time a page was opened, and two scenarios
compared against each other carried sampling noise of their own. The review item
asking for comparison on the same random series could not be satisfied.

simulate_net_worth_forward already seeded its generator; these tests cover the
rule for both and keep an unseeded draw from coming back anywhere.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from backend.app.services import strategy_service
except ModuleNotFoundError:  # inside the container the package is app.*
    from app.services import strategy_service  # type: ignore[no-redef]


ARGS = dict(
    current_funded=1_000_000.0,
    monthly_savings=50_000.0,
    years_remaining=8.0,
    annual_return=5.0,
    contribution_annual_return=7.0,
    volatility=15.0,
    inflation_rate=2.0,
    n_simulations=400,
)


def test_the_same_assumptions_give_the_same_answer():
    first = strategy_service.run_monte_carlo(**ARGS)
    second = strategy_service.run_monte_carlo(**ARGS)
    assert first["percentiles"] == second["percentiles"]
    assert first["year_by_year"] == second["year_by_year"]
    assert first["simulated_end_values"] == second["simulated_end_values"]


def test_probability_of_the_same_goal_does_not_drift_between_reads():
    probability = [
        strategy_service.calculate_goal_probability_monte_carlo(
            target_amount=4_000_000.0, **ARGS
        )
        for _ in range(3)
    ]
    assert len(set(probability)) == 1, probability


def test_two_scenarios_differ_by_the_assumption_that_differs():
    """A better return must read as better, not as noise."""
    lower = strategy_service.run_monte_carlo(**(ARGS | {"annual_return": 3.0}))
    higher = strategy_service.run_monte_carlo(**(ARGS | {"annual_return": 7.0}))
    assert higher["percentiles"]["p50"] > lower["percentiles"]["p50"]
    assert higher["percentiles"]["p10"] > lower["percentiles"]["p10"]
    assert higher["percentiles"]["p90"] > lower["percentiles"]["p90"]


def test_no_unseeded_draw_remains_in_the_backend():
    """Every generator must be built from the one declared seed.

    numpy global calls (np.random.normal, np.random.seed, ...) are irreproducible
    and, worse, share state across requests. default_rng with the declared seed is
    the only form allowed.
    """
    root = Path(strategy_service.__file__).resolve().parents[1]
    allowed = "np.random.default_rng(PROJECTION_SEED)"
    offenders: list[str] = []
    seen = 0
    sources = sorted(root.rglob("*.py"))
    assert len(sources) > 50, f"the scan did not reach the backend: {root}"
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for hit in re.findall(r"np\.random\.[A-Za-z_]+\([^)]*\)", line):
                seen += 1
                if hit != allowed:
                    offenders.append(f"{path.relative_to(root)}:{number}: {hit}")
    assert not offenders, "unseeded or differently seeded draws: " + "; ".join(offenders)
    # Without this the guard would also pass if the draws simply went away.
    assert seen >= 2, f"expected the seeded generators to be found, saw {seen}"
