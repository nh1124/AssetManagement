"""Regression guard for the goal metrics carried by the budget summary (P6-001).

budget_plan_service no longer reaches into the goal domain. The goal-derived
figures now arrive through the `goal_metrics` kwarg, composed by the
life_events router. The response shape must stay identical, because
Strategy.tsx and mobile/pages/Plan.tsx read these keys.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.routers.budget_plans import get_budget_plan_summary as budget_summary_endpoint
    from backend.app.services.budget_plan_service import get_budget_summary
    from backend.app.services.cache_service import invalidate_client
    from backend.app.services.strategy_service import summarize_goal_funding_gap
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers.budget_plans import get_budget_plan_summary as budget_summary_endpoint  # type: ignore[no-redef]
    from app.services.budget_plan_service import get_budget_summary  # type: ignore[no-redef]
    from app.services.cache_service import invalidate_client  # type: ignore[no-redef]
    from app.services.strategy_service import summarize_goal_funding_gap  # type: ignore[no-redef]


PERIOD = "2026-05"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed(db, client_id: int):
    client = models.Client(id=client_id, name=f"c{client_id}", general_settings={}, ai_config={})
    cash = models.Account(client_id=client_id, name="cash", account_type="asset")
    db.add_all([client, cash])
    db.flush()
    db.add(
        models.LifeEvent(
            client_id=client_id,
            name="house",
            target_date=date.today() + timedelta(days=365 * 5),
            target_amount=6_000_000,
            priority=1,
        )
    )
    db.commit()
    return client


def test_budget_summary_defaults_goal_metrics_to_zero_without_the_caller():
    """Planning must stand on its own when no goal metrics are supplied."""
    db = _session()
    try:
        _seed(db, 1)
        summary = get_budget_summary(db, 1, PERIOD)
        assert summary["goals_count"] == 0
        assert summary["total_goal_gap"] == 0
        assert summary["required_monthly_savings"] == 0
    finally:
        db.close()


def test_budget_summary_echoes_supplied_goal_metrics():
    db = _session()
    try:
        _seed(db, 1)
        summary = get_budget_summary(
            db,
            1,
            PERIOD,
            goal_metrics={
                "goals_count": 3,
                "total_goal_gap": 1_200_000,
                "required_monthly_savings": 20_000,
            },
        )
        assert summary["goals_count"] == 3
        assert summary["total_goal_gap"] == 1_200_000
        assert summary["required_monthly_savings"] == 20_000
    finally:
        db.close()


def test_summarize_goal_funding_gap_reports_the_unfunded_goal():
    db = _session()
    try:
        _seed(db, 1)
        metrics = summarize_goal_funding_gap(db, 1)
        assert metrics["goals_count"] == 1
        # Nothing is funded yet, so the whole target is still a gap.
        assert metrics["total_goal_gap"] > 0
        assert metrics["required_monthly_savings"] > 0
    finally:
        db.close()


def test_budget_summary_endpoint_still_returns_goal_metrics():
    """The router is what composes planning and goals; this is the real guard."""
    db = _session()
    try:
        client = _seed(db, 7)
        invalidate_client(7)
        summary = budget_summary_endpoint(
            period=PERIOD,
            plan_id=None,
            cash_flow_start_period=None,
            cash_flow_months=12,
            db=db,
            current_client=client,
        )
        for key in ("required_monthly_savings", "total_goal_gap", "goals_count"):
            assert key in summary, f"{key} disappeared from the budget-summary response"
        assert summary["goals_count"] == 1
        assert summary["total_goal_gap"] > 0
        assert summary["required_monthly_savings"] > 0
    finally:
        invalidate_client(7)
        db.close()
