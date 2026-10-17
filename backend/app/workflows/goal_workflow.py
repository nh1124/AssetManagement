from sqlalchemy.orm import Session

from .. import models, schemas
from ..services.goal_service import create_goal_record
from ..services.milestone_service import build_default_milestone_rows, create_milestone
from ..services.capsule_service import create_capsule_for_goal
from ..services.cache_service import invalidate_client
from ..services.life_scenario_scope import get_goal


def create_goal(
    db: Session, client_id: int, payload: schemas.LifeEventCreate, *, commit: bool = True,
) -> models.LifeEvent:
    # Every step only flushes and the commit comes once at the end, so a failure
    # part way leaves no goal behind for a retry to duplicate.
    db_event = create_goal_record(db, client_id, payload, commit=False)
    # Receipts belong to projections, not to savings capsules or savings milestones.
    if db_event.direction != "income":
        for row in build_default_milestone_rows(db, client_id, db_event.id):
            create_milestone(db, client_id, schemas.MilestoneCreate(**row), commit=False)
        goal = get_goal(db, client_id)
        # A draft story has no real-money earmarks until it becomes the goal.
        if goal is not None and goal.id == db_event.scenario_id:
            create_capsule_for_goal(db, client_id, db_event)
    if commit:
        db.commit()
        db.refresh(db_event)
        invalidate_client(client_id)
    return db_event
