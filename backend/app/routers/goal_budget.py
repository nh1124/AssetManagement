"""HTTP adapters for reflecting the goal scenario into the monthly budget."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..workflows import goal_budget_workflow as workflow

router = APIRouter(prefix="/goal-budget", tags=["goal_budget"])


@router.post("/preview")
def preview(
    payload: schemas.GoalBudgetOptions,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """What a reflection would write; nothing is saved."""
    return workflow.preview(db, current_client.id, payload.model_dump())


@router.post("/apply")
def apply(
    payload: schemas.GoalBudgetApply,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    options = payload.model_dump(exclude={"fingerprint"})
    return workflow.apply(db, current_client.id, options, payload.fingerprint)
