"""HTTP adapters for notifications: list, bring up to date, and record decisions."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..domain.messages import Message, message_of
from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services import notification_service
from ..workflows import notification_workflow

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationDecision(BaseModel):
    action: str  # snooze / dismiss / reopen
    until: datetime | None = None


@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Open notifications and snoozed ones whose time has come; nothing is written."""
    return notification_workflow.listing(db, current_client.id)


@router.post("/sync")
def sync_notifications(
    period: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Recompute every kind for the month, then list."""
    return notification_workflow.sync(db, current_client.id, period)


@router.post("/{notification_id}/decision")
def decide(
    notification_id: int,
    payload: NotificationDecision,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    row = notification_service.get(db, current_client.id, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail=Message("Notification not found", ja="通知が見つかりません。"))
    try:
        row = notification_service.decide(db, row, payload.action, until=payload.until)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=message_of(exc)) from exc
    return notification_service.describe(row)
