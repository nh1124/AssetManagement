"""The record of applied goal reflections: what the budget was last told.

Event progress reads the latest record so an event's monthly amount is the one
the budget carries, and reminders compare it with today's goal.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models


def latest(db: Session, client_id: int) -> models.GoalBudgetReflection | None:
    return db.query(models.GoalBudgetReflection).filter_by(client_id=client_id).order_by(
        models.GoalBudgetReflection.applied_at.desc(), models.GoalBudgetReflection.id.desc(),
    ).first()


def record(
    db: Session, client_id: int, *, scenario_id: int, start_period: str, end_period: str,
    options: dict, summary: dict, events: list[dict],
) -> models.GoalBudgetReflection:
    """Add one record in the caller's transaction."""
    row = models.GoalBudgetReflection(
        client_id=client_id, scenario_id=scenario_id, start_period=start_period, end_period=end_period,
        options=options, summary=summary, events=events,
    )
    db.add(row)
    db.flush()
    return row
