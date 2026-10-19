"""HTTP adapters for the plan page's account editor: an account's month as records."""
from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..workflows import plan_record_workflow as workflow

router = APIRouter(prefix="/plan", tags=["plan"])

PERIOD = Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


@router.get("/{period}/accounts/{account_id}")
def account_month(
    account_id: int,
    period: str = PERIOD,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """The account's sections with the records behind each budget, and its automatic transactions of the month."""
    return workflow.account_view(db, current_client.id, period, account_id)


@router.post("/records")
def add_record(
    payload: schemas.PlanRecordCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return workflow.add_record(db, current_client.id, payload)


@router.put("/records/{record_id}")
def amend_record(
    record_id: int,
    payload: schemas.PlanRecordUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return workflow.amend_record(db, current_client.id, record_id, payload)


@router.delete("/records/{record_id}")
def delete_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return workflow.delete_record(db, current_client.id, record_id)
