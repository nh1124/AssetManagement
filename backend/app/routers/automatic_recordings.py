from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..workflows import automatic_recording_workflow

router = APIRouter(prefix="/automatic-recordings", tags=["automatic-recordings"])


class AutoDepreciationRequest(BaseModel):
    enabled: bool

    model_config = ConfigDict(extra="forbid")


@router.get("/")
def list_automatic_recordings(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return automatic_recording_workflow.list_recordings(db, current_client.id)


@router.post("/process-due")
def process_due_automatic_recordings(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return automatic_recording_workflow.process_due(db, current_client.id)


@router.post("/depreciation/{product_id}/post-due")
def post_due_depreciation(
    product_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return automatic_recording_workflow.post_due_depreciation(db, current_client.id, product_id)


@router.put("/depreciation/{product_id}")
def set_auto_depreciation(
    product_id: int,
    payload: AutoDepreciationRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return automatic_recording_workflow.set_auto_depreciation(
        db, current_client.id, product_id, enabled=payload.enabled,
    )
