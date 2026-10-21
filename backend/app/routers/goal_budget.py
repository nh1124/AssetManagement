"""HTTP adapter for comparing the goal with the plan (making the plan is /plan/reflection)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services import goal_plan_service

router = APIRouter(prefix="/goal-budget", tags=["goal_budget"])


@router.get("/plan-check")
def plan_check(
    period: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Per account: the goal's 積立設定 for the month against the plan; nothing is saved."""
    return goal_plan_service.plan_check(db, current_client.id, period)
