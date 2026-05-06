"""Tests for strategy_service critical paths.

Covers:
- monthly_equivalent_from_contribution_schedule (bonus / one-time handling)
- _period_contribution_from_schedule (per-period accuracy)
- generate_roadmap (schedule accuracy, math.ceil fix, granularity)
- get_goal_simulation_context (schedule overrides monthly_savings)
- get_life_events_with_progress (end-to-end with schedule)
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Works both on host (backend.app.*) and inside Docker container (app.*)
try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.strategy_service import (
        _period_contribution_from_schedule,
        generate_roadmap,
        get_goal_simulation_context,
        get_life_events_with_progress,
        monthly_equivalent_from_contribution_schedule,
    )
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.strategy_service import (  # type: ignore[no-redef]
        _period_contribution_from_schedule,
        generate_roadmap,
        get_goal_simulation_context,
        get_life_events_with_progress,
        monthly_equivalent_from_contribution_schedule,
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client_and_goal(db, target_date: date, target_amount: float = 1_500_000, priority: int = 2):
    client = models.Client(id=1, name="test", general_settings={}, ai_config={})
    db.add(client)
    goal = models.LifeEvent(
        client_id=1,
        name="Test Goal",
        target_date=target_date,
        target_amount=target_amount,
        priority=priority,
    )
    db.add(goal)
    db.flush()
    return client, goal


# ---------------------------------------------------------------------------
# monthly_equivalent_from_contribution_schedule
# ---------------------------------------------------------------------------

def test_monthly_equivalent_monthly_only():
    ref = date(2026, 5, 1)
    target = date(2028, 5, 1)
    schedule = [{"kind": "monthly", "amount": 50000}]
    result = monthly_equivalent_from_contribution_schedule(schedule, ref, target)
    assert result == 50000.0


def test_monthly_equivalent_yearly_bonus_adds_to_monthly():
    ref = date(2026, 5, 1)
    target = date(2028, 5, 1)  # 2-year horizon
    schedule = [
        {"kind": "monthly", "amount": 50000},
        {"kind": "yearly", "amount": 600000, "month": 6},
    ]
    result = monthly_equivalent_from_contribution_schedule(schedule, ref, target)
    # total = 50000*12*2 + 600000*2 = 1_200_000 + 1_200_000 = 2_400_000
    # monthly equiv = 2_400_000 / 2 / 12 = 100_000
    assert abs(result - 100_000.0) < 1.0


def test_monthly_equivalent_one_time_within_horizon():
    ref = date(2026, 5, 1)
    target = date(2028, 5, 1)
    schedule = [
        {"kind": "monthly", "amount": 50000},
        {"kind": "one_time", "amount": 240000, "date": "2027-01-01"},
    ]
    result = monthly_equivalent_from_contribution_schedule(schedule, ref, target)
    # horizon ≈ 2 years; 50000/mo + 240000 one-time → equiv ≈ 60_000/mo
    # Allow ±50 for floating-point day-count precision (731/365.25 ≠ exactly 2)
    assert abs(result - 60_000.0) < 50.0


def test_monthly_equivalent_one_time_outside_horizon_excluded():
    ref = date(2026, 5, 1)
    target = date(2027, 5, 1)
    schedule = [
        {"kind": "monthly", "amount": 50000},
        {"kind": "one_time", "amount": 1_000_000, "date": "2028-01-01"},  # after target
    ]
    result = monthly_equivalent_from_contribution_schedule(schedule, ref, target)
    assert abs(result - 50_000.0) < 1.0


def test_monthly_equivalent_empty_schedule_returns_none():
    ref = date(2026, 5, 1)
    target = date(2028, 5, 1)
    assert monthly_equivalent_from_contribution_schedule([], ref, target) is None
    assert monthly_equivalent_from_contribution_schedule(None, ref, target) is None


def test_monthly_equivalent_zero_amount_excluded():
    ref = date(2026, 5, 1)
    target = date(2028, 5, 1)
    schedule = [{"kind": "monthly", "amount": 0}, {"kind": "yearly", "amount": 0, "month": 6}]
    assert monthly_equivalent_from_contribution_schedule(schedule, ref, target) is None


# ---------------------------------------------------------------------------
# _period_contribution_from_schedule
# ---------------------------------------------------------------------------

def test_period_contribution_monthly_single_month():
    schedule = [{"kind": "monthly", "amount": 50000}]
    assert _period_contribution_from_schedule(schedule, date(2026, 6, 1), date(2026, 7, 1)) == 50000.0


def test_period_contribution_monthly_quarter():
    schedule = [{"kind": "monthly", "amount": 50000}]
    # April–June (3 months)
    assert _period_contribution_from_schedule(schedule, date(2026, 4, 1), date(2026, 7, 1)) == 150000.0


def test_period_contribution_yearly_bonus_in_month():
    schedule = [{"kind": "yearly", "amount": 600000, "month": 6}]
    assert _period_contribution_from_schedule(schedule, date(2026, 6, 1), date(2026, 7, 1)) == 600000.0


def test_period_contribution_yearly_bonus_not_in_month():
    schedule = [{"kind": "yearly", "amount": 600000, "month": 6}]
    assert _period_contribution_from_schedule(schedule, date(2026, 5, 1), date(2026, 6, 1)) == 0.0


def test_period_contribution_one_time_in_period():
    schedule = [{"kind": "one_time", "amount": 300000, "date": "2026-07-15"}]
    assert _period_contribution_from_schedule(schedule, date(2026, 7, 1), date(2026, 8, 1)) == 300000.0


def test_period_contribution_one_time_outside_period():
    schedule = [{"kind": "one_time", "amount": 300000, "date": "2026-08-15"}]
    assert _period_contribution_from_schedule(schedule, date(2026, 7, 1), date(2026, 8, 1)) == 0.0


def test_period_contribution_mixed_monthly_and_bonus():
    schedule = [
        {"kind": "monthly", "amount": 50000},
        {"kind": "yearly", "amount": 600000, "month": 6},
    ]
    # June: 50000 monthly + 600000 bonus
    june = _period_contribution_from_schedule(schedule, date(2026, 6, 1), date(2026, 7, 1))
    assert june == 650000.0
    # May: only monthly
    may = _period_contribution_from_schedule(schedule, date(2026, 5, 1), date(2026, 6, 1))
    assert may == 50000.0


# ---------------------------------------------------------------------------
# generate_roadmap
# ---------------------------------------------------------------------------

def test_generate_roadmap_annual_ceil_fix_for_short_horizon():
    """Goal ~1.9 years away must produce 2 annual rows, not 1 (math.ceil fix)."""
    ref = date(2026, 5, 6)
    target_date = date(2028, 4, 1)  # ≈1.9 years remaining
    years = (target_date - ref).days / 365.25
    rows = generate_roadmap(
        current_funded=0,
        monthly_savings=50000,
        years_remaining=years,
        annual_return=5.0,
        interval="annual",
        reference_date=ref,
    )
    # Row 0 = Current, Row 1 = Year 1, Row 2 = Year 2
    assert len(rows) == 3, f"Expected 3 rows (Current + 2 years), got {len(rows)}: {[r['label'] for r in rows]}"


def test_generate_roadmap_monthly_count():
    ref = date(2026, 5, 1)
    rows = generate_roadmap(
        current_funded=0, monthly_savings=50000, years_remaining=1.0,
        annual_return=5.0, interval="monthly", reference_date=ref,
    )
    assert len(rows) == 13  # row 0 (Current) + 12 months


def test_generate_roadmap_schedule_bonus_in_correct_month():
    """June bonus appears only in June, not spread across all months."""
    ref = date(2026, 5, 1)
    schedule = [
        {"kind": "monthly", "amount": 50000},
        {"kind": "yearly", "amount": 600000, "month": 6},
    ]
    rows = generate_roadmap(
        current_funded=0, monthly_savings=50000, years_remaining=1.0,
        annual_return=0.0, interval="monthly", reference_date=ref,
        contribution_schedule=schedule,
    )
    june = next((r for r in rows if r["label"] == "2026-06"), None)
    assert june is not None
    assert june["contribution"] == 650000.0  # 50000 monthly + 600000 bonus
    for row in rows[1:]:  # skip Current row
        if row["label"] != "2026-06":
            assert row["contribution"] == 50000.0, f"Row {row['label']} should be 50000"


def test_generate_roadmap_schedule_total_equals_averaged_total():
    """Annual total contributions are the same whether using schedule or averaged savings."""
    ref = date(2026, 1, 1)
    schedule = [
        {"kind": "monthly", "amount": 50000},
        {"kind": "yearly", "amount": 600000, "month": 6},
    ]
    rows_sched = generate_roadmap(
        current_funded=0, monthly_savings=50000, years_remaining=1.0,
        annual_return=0.0, interval="monthly", reference_date=ref,
        contribution_schedule=schedule,
    )
    total_sched = sum(r["contribution"] for r in rows_sched)

    rows_avg = generate_roadmap(
        current_funded=0, monthly_savings=100000, years_remaining=1.0,
        annual_return=0.0, interval="monthly", reference_date=ref,
    )
    total_avg = sum(r["contribution"] for r in rows_avg)

    assert abs(total_sched - 1_200_000.0) < 1.0, f"Got {total_sched}"
    assert abs(total_avg - 1_200_000.0) < 1.0, f"Got {total_avg}"


def test_generate_roadmap_no_schedule_uniform_savings():
    """Without schedule, every month gets exactly monthly_savings."""
    ref = date(2026, 5, 1)
    rows = generate_roadmap(
        current_funded=0, monthly_savings=80000, years_remaining=1.0,
        annual_return=0.0, interval="monthly", reference_date=ref,
    )
    for row in rows[1:]:
        assert row["contribution"] == 80000.0


def test_generate_roadmap_end_balance_increases_with_contribution():
    ref = date(2026, 5, 1)
    rows = generate_roadmap(
        current_funded=500000, monthly_savings=50000, years_remaining=1.0,
        annual_return=5.0, interval="monthly", reference_date=ref,
    )
    assert rows[-1]["end_balance"] > rows[0]["end_balance"]


# ---------------------------------------------------------------------------
# get_goal_simulation_context
# ---------------------------------------------------------------------------

def test_goal_context_schedule_overrides_monthly_savings():
    db = _session()
    try:
        _, goal = _client_and_goal(db, target_date=date(2028, 5, 1))
        db.commit()

        schedule = [
            {"kind": "monthly", "amount": 50000},
            {"kind": "yearly", "amount": 600000, "month": 6},
        ]
        ctx = get_goal_simulation_context(
            db, client_id=1, event=goal,
            annual_return=5.0, inflation=2.0,
            monthly_savings=50000,  # should be overridden to ~100000
            contribution_schedule=schedule,
            allocation_mode="direct",
        )
        assert ctx["monthly_savings"] > 50000, "Schedule must override monthly_savings"
        assert abs(ctx["monthly_savings"] - 100_000.0) < 500.0
    finally:
        db.close()


def test_goal_context_no_schedule_uses_monthly_savings():
    db = _session()
    try:
        _, goal = _client_and_goal(db, target_date=date(2028, 5, 1))
        db.commit()

        ctx = get_goal_simulation_context(
            db, 1, goal, annual_return=5.0, inflation=2.0,
            monthly_savings=80000, contribution_schedule=None, allocation_mode="direct",
        )
        assert ctx["monthly_savings"] == 80000.0
    finally:
        db.close()


def test_goal_context_direct_allocation_ratio_is_one():
    db = _session()
    try:
        _, goal = _client_and_goal(db, target_date=date(2028, 5, 1))
        db.commit()

        ctx = get_goal_simulation_context(
            db, 1, goal, monthly_savings=50000, allocation_mode="direct",
        )
        assert ctx["allocated_monthly_savings"] == ctx["monthly_savings"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# get_life_events_with_progress (integration)
# ---------------------------------------------------------------------------

def test_life_events_bonus_raises_projected_amount():
    db = _session()
    try:
        _, goal = _client_and_goal(db, target_date=date(2028, 5, 1), target_amount=1_500_000)
        db.commit()

        events_base = get_life_events_with_progress(
            db, client_id=1, annual_return=5.0, monthly_savings=50000,
            allocation_mode="direct",
        )
        proj_base = events_base[0]["projected_amount"]

        schedule = [
            {"kind": "monthly", "amount": 50000},
            {"kind": "yearly", "amount": 600000, "month": 6},
        ]
        events_bonus = get_life_events_with_progress(
            db, client_id=1, annual_return=5.0, monthly_savings=50000,
            contribution_schedule=schedule, allocation_mode="direct",
        )
        proj_bonus = events_bonus[0]["projected_amount"]

        assert proj_bonus > proj_base, (
            f"Projection with bonus ({proj_bonus:,.0f}) should exceed baseline ({proj_base:,.0f})"
        )
    finally:
        db.close()


def test_life_events_roadmap_bonus_in_exact_month():
    """In direct mode the June bonus must appear in the June roadmap row."""
    db = _session()
    try:
        _, goal = _client_and_goal(db, target_date=date(2028, 5, 1))
        db.commit()

        ref = date(2026, 5, 1)
        schedule = [
            {"kind": "monthly", "amount": 50000},
            {"kind": "yearly", "amount": 600000, "month": 6},
        ]
        events = get_life_events_with_progress(
            db, client_id=1, annual_return=0.0, monthly_savings=50000,
            contribution_schedule=schedule, allocation_mode="direct",
            reference_date=ref, roadmap_interval="monthly",
        )
        roadmap = events[0]["roadmap"]
        june = next((r for r in roadmap if r["label"] == "2026-06"), None)
        assert june is not None, "June 2026 row missing from roadmap"
        assert june["contribution"] == 650_000.0, (
            f"June contribution should be 650_000 (50000 + 600000), got {june['contribution']}"
        )
    finally:
        db.close()


def test_life_events_short_horizon_shows_two_annual_years():
    """Goal ~1.9 years away must have at least 2 annual projection rows."""
    db = _session()
    try:
        _, goal = _client_and_goal(db, target_date=date(2028, 4, 1))
        db.commit()

        ref = date(2026, 5, 6)
        events = get_life_events_with_progress(
            db, client_id=1, annual_return=5.0, monthly_savings=50000,
            reference_date=ref, roadmap_interval="annual",
        )
        roadmap = events[0]["roadmap"]
        assert len(roadmap) >= 3, (
            f"Expected >= 3 rows (Current + 2 years) for ~1.9y horizon, got {len(roadmap)}"
        )
    finally:
        db.close()
