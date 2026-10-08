"""boost_allocation now earmarks capsule holdings instead of GoalAllocation rows.

The goal_allocations table was dropped in migration 20260505_0015 and the model
went with it, so the old implementation raised AttributeError the moment the
action was applied. These tests pin the capsule-based replacement.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.action_bridge_service import apply_action, create_action
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.action_bridge_service import apply_action, create_action  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed(db, *, balance: float = 1_000_000.0):
    client = models.Client(id=1, name="test", general_settings={}, ai_config={})
    savings = models.Account(client_id=1, name="savings", account_type="asset", balance=balance)
    goal = models.LifeEvent(
        client_id=1,
        name="house",
        target_date=date.today() + timedelta(days=365 * 5),
        target_amount=6_000_000,
        priority=1,
    )
    db.add_all([client, savings, goal])
    db.commit()
    return savings, goal


def test_boost_allocation_creates_capsule_holding_for_the_goal():
    db = _session()
    try:
        savings, goal = _seed(db)
        action = create_action(
            db,
            client_id=1,
            source_period="2026-10",
            kind="boost_allocation",
            payload={"life_event_id": goal.id, "account_id": savings.id, "delta_percent": 10},
        )

        applied = apply_action(db, client_id=1, action_id=action["id"])

        assert applied["status"] == "applied"
        result = applied["result"]
        assert result["applied_amount"] == pytest.approx(100_000.0)
        assert result["clamped"] is False

        capsule = db.query(models.Capsule).filter_by(client_id=1, life_event_id=goal.id).one()
        holding = db.query(models.CapsuleHolding).filter_by(
            capsule_id=capsule.id, account_id=savings.id
        ).one()
        assert holding.held_amount == pytest.approx(100_000.0)
        assert capsule.current_balance == pytest.approx(100_000.0)
    finally:
        db.close()


def test_boost_allocation_accumulates_on_repeat():
    db = _session()
    try:
        savings, goal = _seed(db)
        for _ in range(2):
            action = create_action(
                db,
                client_id=1,
                source_period="2026-10",
                kind="boost_allocation",
                payload={"life_event_id": goal.id, "account_id": savings.id, "delta_percent": 10},
            )
            apply_action(db, client_id=1, action_id=action["id"])

        capsule = db.query(models.Capsule).filter_by(client_id=1, life_event_id=goal.id).one()
        holding = db.query(models.CapsuleHolding).filter_by(
            capsule_id=capsule.id, account_id=savings.id
        ).one()
        assert holding.held_amount == pytest.approx(200_000.0)
    finally:
        db.close()


def test_boost_allocation_cannot_earmark_more_than_the_account_holds():
    db = _session()
    try:
        savings, goal = _seed(db, balance=100_000.0)
        # A second goal already claims most of the account.
        other = models.LifeEvent(
            client_id=1,
            name="car",
            target_date=date.today() + timedelta(days=365),
            target_amount=500_000,
            priority=2,
        )
        db.add(other)
        db.flush()
        other_capsule = models.Capsule(
            client_id=1, life_event_id=other.id, name="car",
            target_amount=500_000, monthly_contribution=0, current_balance=0,
        )
        db.add(other_capsule)
        db.flush()
        db.add(models.CapsuleHolding(
            capsule_id=other_capsule.id, account_id=savings.id, held_amount=90_000.0
        ))
        db.commit()

        action = create_action(
            db,
            client_id=1,
            source_period="2026-10",
            kind="boost_allocation",
            payload={"life_event_id": goal.id, "account_id": savings.id, "delta_percent": 50},
        )
        applied = apply_action(db, client_id=1, action_id=action["id"])

        result = applied["result"]
        assert result["requested_amount"] == pytest.approx(50_000.0)
        # Only 10,000 of headroom is left on a 100,000 account.
        assert result["applied_amount"] == pytest.approx(10_000.0)
        assert result["clamped"] is True
    finally:
        db.close()


def test_boost_allocation_rejects_an_unknown_goal():
    db = _session()
    try:
        savings, _goal = _seed(db)
        action = create_action(
            db,
            client_id=1,
            source_period="2026-10",
            kind="boost_allocation",
            payload={"life_event_id": 9999, "account_id": savings.id, "delta_percent": 10},
        )
        with pytest.raises(ValueError):
            apply_action(db, client_id=1, action_id=action["id"])

        refreshed = db.query(models.MonthlyAction).filter_by(id=action["id"]).one()
        assert refreshed.status == "failed"
    finally:
        db.close()
