from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services import automatic_recording_service
from ..workflows import automatic_recording_workflow, plan_reflection_workflow

router = APIRouter(prefix="/automatic-recordings", tags=["automatic-recordings"])


@router.get("/depreciation")
def list_depreciation(db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return automatic_recording_service.depreciation_listing(db, current_client.id)


@router.get("/scheduled")
def list_scheduled_in_period(period: str, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return automatic_recording_service.scheduled_in_period(db, current_client.id, period)


@router.get("/generated")
def list_generated_in_period(period: str, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return automatic_recording_service.generated_in_period(db, current_client.id, period)


@router.post("/process-due")
def process_due_automatic_recordings(db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    """Sign-in: the automatic recordings due, then the start-of-month 自動反映 (WP27) when it has not run yet."""
    result = automatic_recording_workflow.process_due(db, current_client.id)
    plan_reflection_workflow.run_due_logged(db, current_client.id)
    return result
