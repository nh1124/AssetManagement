"""Tests for milestone_service schedule-aware deterministic simulation.

Covers:
- _deterministic_balance_with_schedule: per-period balance vs averaged
- _simulation_value_at: dispatches to schedule path for deterministic
- preview_milestones_from_simulation: quarterly milestones reflect bonus timing
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.milestone_service import (
        _deterministic_balance_with_schedule,
        _simulation_value_at,
        preview_milestones_from_simulation,
    )
    from backend.app.services.strategy_service import (
        calculate_projection,
        get_goal_simulation_context,
    )
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.milestone_service import (  # type: ignore[no-redef]
        _deterministic_balance_with_schedule,
        _simulation_value_at,
        preview_milestones_from_simulation,
    )
    from app.services.strategy_service import (  # type: ignore[no-redef]
        calculate_projection,
        get_goal_simulation_context,
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _setup(db, target_date: date, target_amount: float = 2_000_000):
    client = models.Client(id=1, name="test", general_settings={}, ai_config={})
    db.add(client)
    goal = models.LifeEvent(
        client_id=1,
        name="Test Goal",
        target_date=target_date,
        target_amount=target_amount,
        priority=2,
    )
    db.add(goal)
    db.flush()
    return client, goal


# ---------------------------------------------------------------------------
# _deterministic_balance_with_schedule
# ---------------------------------------------------------------------------

def _make_context(schedule, reference_date, target_date, annual_return=0.0, current_funded=0.0):
    """Build a minimal context dict mimicking get_goal_simulation_context output."""
    return {
        "current_funded": current_funded,
        "monthly_savings": 100_000.0,
        "allocated_monthly_savings": 100_000.0,
        "effective_return": annual_return,
        "inflation_rate": 2.0,
        "contribution_schedule": schedule,
        "allocation_mode": "direct",
        "reference_date": reference_date,
    }


def test_deterministic_no_schedule_falls_back_to_calculate_projection():
    """Empty schedule must delegate to calculate_projection, not month-loop."""
    ref = date(2026, 5, 1)
    target = date(2027, 5, 1)
    ctx = _make_context([], ref, target, annual_return=0.0, current_funded=0.0)
    result = _deterministic_balance_with_schedule(
        context=ctx, reference_date=ref, target_date=target
    )
    years = (target - ref).days / 365.25
    expected = calculate_projection(
        current_funded=0.0,
        monthly_savings=100_000.0,
        years_remaining=years,
        annual_return=0.0,
    )
    assert abs(result - expected) < 1.0


def test_deterministic_monthly_only_matches_averaged():
    ref = date(2026, 5, 1)
    target = date(2027, 5, 1)
    schedule = [{"kind": "monthly", "amount": 100_000}]
    ctx = _make_context(schedule, ref, target, annual_return=0.0, current_funded=0.0)
    result = _deterministic_balance_with_schedule(
        context=ctx, reference_date=ref, target_date=target
    )
    assert abs(result - 1_200_000.0) < 1.0


def test_deterministic_yearly_bonus_appears_in_exact_month():
    """With a June bonus, balance at July 1 must be higher than at May 31."""
    ref = date(2026, 5, 1)
    schedule = [
        {"kind": "monthly", "amount": 50_000},
        {"kind": "yearly", "amount": 600_000, "month": 6},
    ]
    ctx_before = _make_context(schedule, ref, date(2026, 6, 1), annual_return=0.0)
    ctx_after = _make_context(schedule, ref, date(2026, 7, 1), annual_return=0.0)

    bal_before = _deterministic_balance_with_schedule(
        context=ctx_before, reference_date=ref, target_date=date(2026, 6, 1)
    )
    bal_after = _deterministic_balance_with_schedule(
        context=ctx_after, reference_date=ref, target_date=date(2026, 7, 1)
    )
    # Before June: only May's 50_000 (May is the cursor month starting May 1)
    assert abs(bal_before - 50_000.0) < 1.0
    # After June: 50_000 (May) + 650_000 (June: 50_000 + 600_000) = 700_000
    assert abs(bal_after - 700_000.0) < 1.0


def test_deterministic_one_time_reflected_in_period():
    ref = date(2026, 5, 1)
    schedule = [
        {"kind": "monthly", "amount": 50_000},
        {"kind": "one_time", "amount": 500_000, "date": "2026-08-01"},
    ]
    ctx_before = _make_context(schedule, ref, date(2026, 8, 1), annual_return=0.0)
    ctx_after = _make_context(schedule, ref, date(2026, 9, 1), annual_return=0.0)

    bal_before = _deterministic_balance_with_schedule(
        context=ctx_before, reference_date=ref, target_date=date(2026, 8, 1)
    )
    bal_after = _deterministic_balance_with_schedule(
        context=ctx_after, reference_date=ref, target_date=date(2026, 9, 1)
    )
    # Before Aug: 3 months × 50_000 = 150_000
    assert abs(bal_before - 150_000.0) < 1.0
    # After Aug: 150_000 + 550_000 (50_000 + 500_000 one-time) = 700_000
    assert abs(bal_after - 700_000.0) < 1.0


def test_deterministic_allocation_ratio_applied():
    """In weighted mode (ratio < 1.0) contributions are scaled down."""
    ref = date(2026, 5, 1)
    target = date(2026, 7, 1)
    schedule = [{"kind": "monthly", "amount": 100_000}]
    ctx = {
        "current_funded": 0.0,
        "monthly_savings": 100_000.0,
        "allocated_monthly_savings": 50_000.0,  # ratio = 0.5
        "effective_return": 0.0,
        "inflation_rate": 2.0,
        "contribution_schedule": schedule,
        "allocation_mode": "weighted",
        "reference_date": ref,
    }
    result = _deterministic_balance_with_schedule(
        context=ctx, reference_date=ref, target_date=target
    )
    # 2 months × 100_000 × 0.5 = 100_000
    assert abs(result - 100_000.0) < 1.0


# ---------------------------------------------------------------------------
# _simulation_value_at dispatch
# ---------------------------------------------------------------------------

def test_simulation_value_at_deterministic_uses_schedule_when_milestone_date_given():
    ref = date(2026, 5, 1)
    schedule = [
        {"kind": "monthly", "amount": 50_000},
        {"kind": "yearly", "amount": 600_000, "month": 6},
    ]
    ctx = _make_context(schedule, ref, date(2027, 5, 1), annual_return=0.0)
    # July milestone — should include June bonus
    result = _simulation_value_at(
        basis="deterministic",
        years_elapsed=2 / 12,
        context=ctx,
        volatility=15.0,
        n_simulations=200,
        milestone_date=date(2026, 7, 1),
    )
    assert abs(result - 700_000.0) < 1.0


def test_simulation_value_at_deterministic_no_date_uses_averaged():
    """Without milestone_date, falls back to calculate_projection (averaged)."""
    ref = date(2026, 5, 1)
    schedule = [{"kind": "monthly", "amount": 100_000}]
    ctx = _make_context(schedule, ref, date(2027, 5, 1), annual_return=0.0)
    result = _simulation_value_at(
        basis="deterministic",
        years_elapsed=1.0,
        context=ctx,
        volatility=15.0,
        n_simulations=200,
        milestone_date=None,
    )
    assert abs(result - 1_200_000.0) < 1.0


def test_simulation_value_at_mc_still_uses_averaged():
    """MC basis always uses allocated_monthly_savings (by design)."""
    ref = date(2026, 5, 1)
    schedule = [
        {"kind": "monthly", "amount": 50_000},
        {"kind": "yearly", "amount": 600_000, "month": 6},
    ]
    ctx = _make_context(schedule, ref, date(2028, 5, 1), annual_return=5.0)
    ctx["monthly_savings"] = 100_000.0
    ctx["allocated_monthly_savings"] = 100_000.0
    result = _simulation_value_at(
        basis="p50",
        years_elapsed=1.0,
        context=ctx,
        volatility=15.0,
        n_simulations=500,
        milestone_date=date(2027, 5, 1),
    )
    assert result > 0


# ---------------------------------------------------------------------------
# preview_milestones_from_simulation — quarterly with bonus
# ---------------------------------------------------------------------------

def test_preview_milestones_quarterly_bonus_reflected():
    """Quarterly deterministic milestones after June must reflect the bonus."""
    db = _session()
    try:
        _, goal = _setup(db, target_date=date(2028, 5, 1))
        db.commit()

        ref = date(2026, 5, 1)
        schedule = [
            {"kind": "monthly", "amount": 50_000},
            {"kind": "yearly", "amount": 600_000, "month": 6},
        ]
        preview = preview_milestones_from_simulation(
            db, client_id=1, life_event_id=goal.id,
            basis="deterministic",
            interval="quarterly",
            annual_return=0.0,
            monthly_savings=50_000,
            contribution_schedule=schedule,
            allocation_mode="direct",
        )
        items = preview["items"]
        # First quarterly milestone ≈ 3 months from ref (Aug 1):
        # May 50k + Jun 650k + Jul 50k = 750_000
        aug_item = next(
            (it for it in items if it["date"].month == 8 and it["date"].year == 2026),
            None,
        )
        assert aug_item is not None, "August 2026 milestone missing"
        assert aug_item["target_amount"] > 700_000, (
            f"Aug milestone should reflect June bonus, got {aug_item['target_amount']:,.0f}"
        )

        # June bonus falls in Q1 (May–Jul), so schedule path must be HIGHER than
        # the averaged path (which spreads 100k/month uniformly — no bonus spike).
        preview_avg = preview_milestones_from_simulation(
            db, client_id=1, life_event_id=goal.id,
            basis="deterministic",
            interval="quarterly",
            annual_return=0.0,
            monthly_savings=100_000,  # averaged equivalent (no bonus timing)
            contribution_schedule=None,
            allocation_mode="direct",
        )
        first_avg = preview_avg["items"][0] if preview_avg["items"] else None
        if first_avg:
            assert aug_item["target_amount"] > first_avg["target_amount"], (
                "Schedule path (with June bonus) must exceed averaged path for Q1 milestone: "
                f"schedule={aug_item['target_amount']:,.0f}, avg={first_avg['target_amount']:,.0f}"
            )
    finally:
        db.close()
