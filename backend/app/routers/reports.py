from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services.report_service import (
    apply_monthly_report_proposal,
    apply_period_report_proposal,
    generate_monthly_report,
    generate_period_report,
)

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


@router.get("/period")
def get_period_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return generate_period_report(db, current_client.id, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/period/actions/{proposal_id}/apply")
def apply_period_report_action(
    proposal_id: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return apply_period_report_proposal(db, current_client.id, start_date, end_date, proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{period}/actions/{proposal_id}/apply")
def apply_monthly_report_action(
    period: str,
    proposal_id: str,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return apply_monthly_report_proposal(db, current_client.id, period, proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
