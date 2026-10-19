"""HTTP adapters for making the plan from the goal."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import goal_plan_service
from ..workflows import goal_budget_workflow as workflow

router = APIRouter(prefix="/goal-budget", tags=["goal_budget"])


@router.get("/plan-check")
def plan_check(
    period: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Per account: the goal's 積立設定 for the month against the plan; nothing is saved."""
    return goal_plan_service.plan_check(db, current_client.id, period)


@router.post("/preview")
def preview(
    payload: schemas.GoalPlanRange,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """What making the plan would write; nothing is saved."""
    return workflow.preview(db, current_client.id, payload.start_period, payload.end_period)


@router.post("/apply")
def apply(
    payload: schemas.GoalPlanApply,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return workflow.apply(db, current_client.id, payload.start_period, payload.end_period, payload.fingerprint)
