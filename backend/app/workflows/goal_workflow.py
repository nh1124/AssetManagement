from sqlalchemy.orm import Session

from .. import models, schemas
from ..services.goal_service import create_goal_record
from ..services.milestone_service import (
    build_default_milestone_rows,
    create_milestone,
    reset_milestones_from_annual_plan,
)
from ..services.capsule_service import create_capsule_for_goal
from ..services.cache_service import invalidate_client


def create_goal(
    db: Session, client_id: int, payload: schemas.LifeEventCreate, *, commit: bool = True,
) -> models.LifeEvent:
    db_event = create_goal_record(db, client_id, payload, commit=commit)
    if db_event.direction == "income":
        # Receipts belong to projections, not to savings capsules or savings milestones.
        if commit:
            invalidate_client(client_id)
        return db_event
    if commit:
        reset_milestones_from_annual_plan(db, client_id, db_event.id)
    else:
        # The reset helper commits internally. A new goal has nothing to reset,
        # so use the milestone owner's primitives to keep the caller's transaction open.
        for row in build_default_milestone_rows(db, client_id, db_event.id):
            create_milestone(db, client_id, schemas.MilestoneCreate(**row), commit=False)
    create_capsule_for_goal(db, client_id, db_event)
    if commit:
        db.commit()
        db.refresh(db_event)
        invalidate_client(client_id)
    return db_event
