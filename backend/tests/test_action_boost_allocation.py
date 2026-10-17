"""boost_allocation earmarks cash with attributed, balanced journal entries."""
from __future__ import annotations

from scenario_fixtures import goal_scenario_id

from app.services.money_storage import to_minor
from app.services.ledger_service import create_transaction
from app.services.capsule_service import claimed_minor
from app.domain.journal import Leg


from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.workflows.monthly_action_workflow import apply_action, create_action
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.workflows.monthly_action_workflow import apply_action, create_action  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed(db, *, balance: float = 1_000_000.0):
    client = models.Client(id=1, name="test", general_settings={}, ai_config={})
    savings = models.Account(client_id=1, name="savings", account_type="asset")
    goal = models.LifeEvent(scenario_id=goal_scenario_id(db, 1),
        client_id=1,
        name="house",
        target_date=date.today() + timedelta(days=365 * 5),
        target_amount_minor=to_minor(6_000_000, "JPY"),
        priority=1,
    )
    db.add_all([client, savings, goal])
    db.commit()
    opening = models.Account(client_id=1, name="opening equity", account_type="income")
    db.add(opening)
    db.flush()
    create_transaction(db, client_id=1, date=date(2026, 1, 1), description="Opening holdings",
                       amount_minor=to_minor(balance, "JPY"), currency="JPY",
                       from_account_id=opening.id, to_account_id=savings.id)
    db.commit()
    return savings, goal


def test_boost_allocation_creates_journal_claim_for_the_goal():
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
        assert claimed_minor(db, 1, capsule.id, savings.id) == {"JPY": 100_000}
        assert result["capsule_balance"] == 100_000
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
        assert claimed_minor(db, 1, capsule.id, savings.id) == {"JPY": 200_000}
    finally:
        db.close()


def test_boost_allocation_cannot_earmark_more_than_the_account_holds():
    db = _session()
    try:
        savings, goal = _seed(db, balance=100_000.0)
        # A second goal already claims most of the account.
        other = models.LifeEvent(scenario_id=goal_scenario_id(db, 1),
            client_id=1,
            name="car",
            target_date=date.today() + timedelta(days=365),
            target_amount_minor=to_minor(500_000, "JPY"),
            priority=2,
        )
        db.add(other)
        db.flush()
        other_capsule = models.Capsule(
            client_id=1, life_event_id=other.id, name="car",
            target_amount_minor=to_minor(500_000, "JPY"), monthly_contribution_minor=to_minor(0, "JPY"),
        )
        db.add(other_capsule)
        db.flush()
        create_transaction(db, client_id=1, date=date(2026, 1, 1), description="Other claim",
                           amount_minor=90000, currency="JPY",
                           legs=[Leg(savings.id, debit=90000, capsule_id=other_capsule.id),
                                 Leg(savings.id, credit=90000)])
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


def test_boost_allocation_release_clamps_to_claim_and_preserves_account_money():
    from app.services.ledger_valuation import calculate_account_valued_balance
    db = _session()
    try:
        savings, goal = _seed(db, balance=100_000)
        for percent in [10, -50]:
            action = create_action(db, client_id=1, source_period="2026-10", kind="boost_allocation",
                                   payload={"life_event_id": goal.id, "account_id": savings.id, "delta_percent": percent})
            result = apply_action(db, client_id=1, action_id=action["id"])["result"]
            assert calculate_account_valued_balance(db, savings) == 100_000
            if percent == 10:
                assert result["capsule_balance"] == 10_000
            else:
                assert result["applied_amount"] == -10_000
                assert result["claimed_amount"] == result["capsule_balance"] == 0
        for transaction in db.query(models.Transaction):
            assert sum(leg.debit_minor for leg in transaction.journal_entries) == sum(leg.credit_minor for leg in transaction.journal_entries) == transaction.amount_minor
    finally:
        db.close()
