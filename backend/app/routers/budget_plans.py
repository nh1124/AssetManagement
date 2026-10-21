from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.budget_plan_service import get_budget_summary as build_budget_summary
from ..services.budget_plan_store import (
    copy_period_lines,
    create_plan_lines,
    delete_plan_line as delete_stored_plan_line,
    update_plan_lines,
)
from ..services.cache_service import get_or_set
from ..services.goal_earmark_service import funding_gap

router = APIRouter(prefix="/budget-plans", tags=["budget_plans"])


@router.post("/copy-period")
def copy_period_full_replace(
    payload: schemas.CopyPeriodRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    copied = copy_period_lines(db, current_client.id, payload.source_period, payload.target_period, commit=True)
    invalidate_client(current_client.id)
    return {"status": "success", "copied": copied}


@router.get("/summary")
def get_budget_plan_summary(
    period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    cash_flow_start_period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    cash_flow_months: int = Query(12, ge=1, le=36),
    include_unset: bool = Query(False, description="Add unset_lines: active accounts no plan line covers"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get monthly cash-flow plan summary."""
    if not period:
        period = datetime.now().strftime("%Y-%m")
    try:
        key = (
            f"client:{current_client.id}:budget_summary:{period}:"
            f"{cash_flow_start_period}:{cash_flow_months}:{include_unset}"
        )
        return get_or_set(
            key,
            120,
            lambda: build_budget_summary(
                db,
                current_client.id,
                period,
                cash_flow_start_period=cash_flow_start_period,
                cash_flow_months=cash_flow_months,
                goal_metrics=funding_gap(db, current_client.id),
                include_unset=include_unset,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/lines")
def get_plan_lines(
    period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not period:
        period = datetime.now().strftime("%Y-%m")
    try:
        return build_budget_summary(db, current_client.id, period)["plan_lines"]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/lines")
def create_plan_lines_endpoint(
    lines: List[schemas.MonthlyPlanLineCreate],
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        saved = create_plan_lines(db, current_client.id, lines)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    invalidate_client(current_client.id)
    return {"status": "success", "ids": [line.id for line in saved]}


@router.put("/lines/batch")
def update_plan_lines_endpoint(
    lines: List[schemas.MonthlyPlanLineBatchUpdate],
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        saved = update_plan_lines(db, current_client.id, lines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    invalidate_client(current_client.id)
    return {"status": "success", "ids": [line.id for line in saved]}


@router.delete("/lines/{line_id}")
def delete_plan_line(
    line_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not delete_stored_plan_line(db, current_client.id, line_id):
        raise HTTPException(status_code=404, detail="Monthly plan line not found")
    invalidate_client(current_client.id)
    return {"message": "Monthly plan line deleted"}
