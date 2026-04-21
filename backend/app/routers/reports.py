from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services.report_service import generate_monthly_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/monthly")
def get_monthly_report(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    return generate_monthly_report(db, current_client.id, year, month)
