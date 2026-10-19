"""The record of applied goal-to-plan reflections: which months the plan was made for."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models


def covering(db: Session, client_id: int, period: str) -> models.GoalBudgetReflection | None:
    """The latest applied reflection whose months include this one."""
    return db.query(models.GoalBudgetReflection).filter(
        models.GoalBudgetReflection.client_id == client_id,
        models.GoalBudgetReflection.start_period <= period,
        models.GoalBudgetReflection.end_period >= period,
    ).order_by(models.GoalBudgetReflection.applied_at.desc(), models.GoalBudgetReflection.id.desc()).first()


def record(
    db: Session, client_id: int, *, scenario_id: int, start_period: str, end_period: str, summary: dict,
) -> models.GoalBudgetReflection:
    """Add one record in the caller's transaction."""
    row = models.GoalBudgetReflection(
        client_id=client_id, scenario_id=scenario_id, start_period=start_period, end_period=end_period, summary=summary,
    )
    db.add(row)
    db.flush()
    return row
