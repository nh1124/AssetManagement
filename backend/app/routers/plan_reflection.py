"""HTTP adapters for 計画への反映 (WP27): its settings, what a run would change, a run on request, its history."""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import goal_budget_record
from ..workflows import plan_reflection_workflow as workflow

router = APIRouter(prefix="/plan/reflection", tags=["plan_reflection"])


@router.get("")
def reflection(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """The settings, the months a run writes and the latest runs; nothing is saved."""
    return {"settings": workflow.settings(db, current_client.id), "periods": workflow.current_range(db, current_client.id),
            "history": goal_budget_record.history(db, current_client.id)}


@router.put("/settings")
def save_settings(
    payload: schemas.ReflectionSettingsPatch,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Save the settings; with 自動反映 on the plan follows them at once."""
    return workflow.save_settings(db, current_client.id, payload.model_dump(exclude_none=True))


@router.post("/preview")
def preview(
    payload: schemas.ReflectionSettingsPatch = Body(default_factory=schemas.ReflectionSettingsPatch),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """What a run would change now, with the saved settings or these changed ones; nothing is saved."""
    return workflow.preview(db, current_client.id, payload.model_dump(exclude_none=True))


@router.post("/run")
def run(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """今すぐ反映: write this month and the 11 after it now, as the settings say."""
    return workflow.run(db, current_client.id, "manual")
