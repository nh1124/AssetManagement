from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.budget_context import BudgetContext
from ..services.budget_plan_service import get_budget_summary as build_budget_summary
from ..services.budget_plan_store import (
    create_plan,
    create_plan_lines,
    delete_plan,
    delete_plan_line as delete_stored_plan_line,
    list_plans,
    replace_plan_lines_from_plan,
    resolve_budget_plan_id,
    set_default_budget_plan,
    update_plan,
    update_plan_lines,
)
from ..services.budget_projection import get_cash_flow_projection, liquid_cash
from ..services.cache_service import get_or_set
from ..services.goal_service import summarize_goal_funding_gap

router = APIRouter(prefix="/budget-plans", tags=["budget_plans"])


@router.get("", response_model=List[schemas.BudgetPlan])
def list_budget_plans(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return list_plans(db, current_client.id)


@router.post("", response_model=schemas.BudgetPlan)
def create_budget_plan(
    payload: schemas.BudgetPlanCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        plan = create_plan(db, current_client.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    invalidate_client(current_client.id)
    return plan


@router.get("/compare", response_model=List[schemas.BudgetPlanCompareResult])
def compare_budget_plans(
    plan_ids: str = Query(..., description="Comma-separated plan IDs"),
    start_period: str = Query(..., description="Format: YYYY-MM"),
    months: int = Query(12, ge=1, le=36),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        id_list = [int(pid.strip()) for pid in plan_ids.split(",") if pid.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="plan_ids must be comma-separated integers")
    if not id_list:
        raise HTTPException(status_code=400, detail="plan_ids must include at least one plan")

    plans = (
        db.query(models.BudgetPlan)
        .filter(
            models.BudgetPlan.client_id == current_client.id,
            models.BudgetPlan.id.in_(id_list),
        )
        .all()
    )
    plans_by_id = {plan.id: plan for plan in plans}
    missing = [plan_id for plan_id in id_list if plan_id not in plans_by_id]
    if missing:
        raise HTTPException(status_code=404, detail="Budget plan not found")

    results = []
    starting_cash = liquid_cash(BudgetContext(db, current_client.id))
    for plan_id in id_list:
        plan = plans_by_id[plan_id]
        projection = get_cash_flow_projection(
            db, current_client.id, start_period, months=months,
            starting_cash=starting_cash, plan_id=plan_id,
        )
        results.append(schemas.BudgetPlanCompareResult(
            plan_id=plan_id,
            plan_name=plan.name,
            cash_flow=[
                schemas.BudgetPlanCashFlowRow(
                    period=row["period"],
                    ending_cash=row["ending_cash"],
                    net_cash=row["net_cash"],
                )
                for row in projection
            ],
        ))
    return results


@router.post("/copy-period")
def copy_period_full_replace(
    payload: schemas.CopyPeriodRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        plan_id = resolve_budget_plan_id(db, current_client.id, payload.plan_id)
        copied = replace_plan_lines_from_plan(
            db, current_client.id, plan_id, plan_id,
            source_period=payload.source_period,
            target_period=payload.target_period,
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Budget plan not found")
    invalidate_client(current_client.id)
    return {"status": "success", "copied": copied}


@router.get("/summary")
def get_budget_plan_summary(
    period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    plan_id: Optional[int] = Query(None, description="Budget plan ID"),
    cash_flow_start_period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    cash_flow_months: int = Query(12, ge=1, le=36),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get monthly cash-flow plan summary."""
    if not period:
        period = datetime.now().strftime("%Y-%m")
    try:
        key = (
            f"client:{current_client.id}:budget_summary:{period}:{plan_id}:"
            f"{cash_flow_start_period}:{cash_flow_months}"
        )
        return get_or_set(
            key,
            120,
            lambda: build_budget_summary(
                db,
                current_client.id,
                period,
                plan_id=plan_id,
                cash_flow_start_period=cash_flow_start_period,
                cash_flow_months=cash_flow_months,
                goal_metrics=summarize_goal_funding_gap(db, current_client.id),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/lines")
def get_plan_lines(
    period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    plan_id: Optional[int] = Query(None, description="Budget plan ID"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not period:
        period = datetime.now().strftime("%Y-%m")
    try:
        return build_budget_summary(db, current_client.id, period, plan_id=plan_id)["plan_lines"]
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

@router.post("/{plan_id}/copy-from")
def copy_plan_from(
    plan_id: int,
    source_plan_id: int = Query(..., description="Source plan ID to copy lines from"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if plan_id == source_plan_id:
        raise HTTPException(status_code=400, detail="Cannot copy a budget plan from itself")
    try:
        copied = replace_plan_lines_from_plan(db, current_client.id, plan_id, source_plan_id, commit=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_client(current_client.id)
    return {"status": "success", "copied": copied}


@router.post("/{plan_id}/adopt", response_model=schemas.BudgetPlan)
def adopt_budget_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        default_plan = set_default_budget_plan(db, current_client.id, plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_client(current_client.id)
    return default_plan


@router.put("/{plan_id}", response_model=schemas.BudgetPlan)
def update_budget_plan(
    plan_id: int,
    payload: schemas.BudgetPlanUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        plan = update_plan(db, current_client.id, plan_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Budget plan not found")
    invalidate_client(current_client.id)
    return plan


@router.delete("/{plan_id}")
def delete_budget_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        deleted = delete_plan(db, current_client.id, plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Budget plan not found")
    invalidate_client(current_client.id)
    return {"message": "Budget plan deleted"}
