from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services import period_close_service

router = APIRouter(prefix="/period-closes", tags=["period-closes"])


class PeriodCloseRequest(BaseModel):
    period: str
    note: str | None = None


class PeriodCloseResponse(PeriodCloseRequest):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: int
    closed_at: datetime


@router.get("", response_model=list[PeriodCloseResponse])
def list_period_closes(db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return period_close_service.list_closes(db, current_client.id)


@router.post("", response_model=PeriodCloseResponse)
def close_period(payload: PeriodCloseRequest, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return period_close_service.close_period(db, current_client.id, payload.period, note=payload.note)


@router.delete("/{period}")
def reopen_period(period: str, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    period_close_service.reopen_period(db, current_client.id, period)
    return {"message": "締めを解除しました。"}
