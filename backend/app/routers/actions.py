from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services.action_bridge_service import (
    apply_action,
    create_action,
    list_actions,
    process_due_actions,
    skip_action,
)

router = APIRouter(prefix="/actions", tags=["actions"])


class ActionCreate(BaseModel):
    source_period: str
    target_period: str | None = None
    kind: str
    description: str = ""
    payload: dict


@router.get("/")
def read_actions(
    source_period: str | None = Query(None),
    target_period: str | None = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return list_actions(db, current_client.id, source_period, target_period)


@router.post("/")
def create_monthly_action(
    payload: ActionCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return create_action(
            db=db,
            client_id=current_client.id,
            source_period=payload.source_period,
            target_period=payload.target_period,
            kind=payload.kind,
            description=payload.description,
            payload=payload.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/process-due")
def process_due_monthly_actions(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return {"processed": process_due_actions(db, current_client.id)}


@router.post("/{action_id}/apply")
def apply_monthly_action(
    action_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return apply_action(db, current_client.id, action_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{action_id}/skip")
def skip_monthly_action(
    action_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return skip_action(db, current_client.id, action_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
