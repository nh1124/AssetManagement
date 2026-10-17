"""HTTP adapters for reflecting the goal scenario into the monthly budget."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..workflows import goal_budget_workflow as workflow

router = APIRouter(prefix="/goal-budget", tags=["goal_budget"])


@router.get("/status")
def status(
    period: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """The savings breakdown for the month and the reasons to reflect again; nothing is saved."""
    return workflow.status(db, current_client.id, period)


@router.post("/sync-action")
def sync_action(
    period: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Create, refresh or set aside the confirmation-required reflection action for the month."""
    return workflow.sync_reflection_action(db, current_client.id, period)


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
    options = payload.model_dump(exclude={"fingerprint", "update_baseline"})
    return workflow.apply(db, current_client.id, options, payload.fingerprint, update_baseline=payload.update_baseline)
