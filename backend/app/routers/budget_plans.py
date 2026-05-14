from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.budget_plan_service import (
    get_or_create_default_plan,
    get_cash_flow_projection,
    _liquid_cash,
    resolve_budget_plan_id,
)

router = APIRouter(prefix="/budget-plans", tags=["budget_plans"])


@router.get("", response_model=List[schemas.BudgetPlan])
def list_budget_plans(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    plans = (
        db.query(models.BudgetPlan)
        .filter(models.BudgetPlan.client_id == current_client.id)
        .order_by(models.BudgetPlan.sort_order, models.BudgetPlan.id)
        .all()
    )
    if not plans:
        default = get_or_create_default_plan(db, current_client.id)
        plans = [default]
    return plans


@router.post("", response_model=schemas.BudgetPlan)
def create_budget_plan(
    payload: schemas.BudgetPlanCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    existing = (
        db.query(models.BudgetPlan)
        .filter_by(client_id=current_client.id, name=payload.name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A plan with this name already exists")
    plan = models.BudgetPlan(
        client_id=current_client.id,
        name=payload.name,
        description=payload.description,
        is_default=False,
        sort_order=payload.sort_order,
    )
    db.add(plan)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A plan with this name already exists") from exc
    db.refresh(plan)
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
    starting_cash = _liquid_cash(db, current_client.id)
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
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Budget plan not found")

    source_lines = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == current_client.id,
            models.MonthlyPlanLine.plan_id == plan_id,
            models.MonthlyPlanLine.target_period == payload.source_period,
            models.MonthlyPlanLine.is_active.is_(True),
        )
        .all()
    )

    # Soft-delete all existing lines in target period
    (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == current_client.id,
            models.MonthlyPlanLine.plan_id == plan_id,
            models.MonthlyPlanLine.target_period == payload.target_period,
        )
        .update({"is_active": False})
    )

    # Insert verbatim copies of source lines into target period
    for src in source_lines:
        new_line = models.MonthlyPlanLine(
            client_id=current_client.id,
            plan_id=plan_id,
            target_period=payload.target_period,
            line_type=src.line_type,
            target_type=src.target_type,
            target_id=src.target_id,
            account_id=src.account_id,
            source_account_id=src.source_account_id,
            name=src.name,
            amount=src.amount,
            source=src.source,
            recurring_transaction_id=src.recurring_transaction_id,
            is_active=True,
        )
        db.add(new_line)

    db.commit()
    return {"status": "success", "copied": len(source_lines)}


@router.post("/{plan_id}/copy-from")
def copy_plan_from(
    plan_id: int,
    source_plan_id: int = Query(..., description="Source plan ID to copy lines from"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if plan_id == source_plan_id:
        raise HTTPException(status_code=400, detail="Cannot copy a budget plan from itself")
    target_plan = db.query(models.BudgetPlan).filter_by(id=plan_id, client_id=current_client.id).first()
    if not target_plan:
        raise HTTPException(status_code=404, detail="Target budget plan not found")
    source_plan = db.query(models.BudgetPlan).filter_by(id=source_plan_id, client_id=current_client.id).first()
    if not source_plan:
        raise HTTPException(status_code=404, detail="Source budget plan not found")

    source_lines = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == current_client.id,
            models.MonthlyPlanLine.plan_id == source_plan_id,
            models.MonthlyPlanLine.is_active.is_(True),
        )
        .all()
    )

    # Soft-delete all existing lines in the target plan
    (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == current_client.id,
            models.MonthlyPlanLine.plan_id == plan_id,
        )
        .update({"is_active": False})
    )

    for src in source_lines:
        new_line = models.MonthlyPlanLine(
            client_id=current_client.id,
            plan_id=plan_id,
            target_period=src.target_period,
            line_type=src.line_type,
            target_type=src.target_type,
            target_id=src.target_id,
            account_id=src.account_id,
            source_account_id=src.source_account_id,
            name=src.name,
            amount=src.amount,
            source=src.source,
            recurring_transaction_id=src.recurring_transaction_id,
            is_active=True,
        )
        db.add(new_line)

    db.commit()
    return {"status": "success", "copied": len(source_lines)}


@router.put("/{plan_id}", response_model=schemas.BudgetPlan)
def update_budget_plan(
    plan_id: int,
    payload: schemas.BudgetPlanUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    plan = db.query(models.BudgetPlan).filter_by(id=plan_id, client_id=current_client.id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Budget plan not found")
    if payload.name is not None:
        duplicate = db.query(models.BudgetPlan).filter(
            models.BudgetPlan.client_id == current_client.id,
            models.BudgetPlan.name == payload.name,
            models.BudgetPlan.id != plan_id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="A plan with this name already exists")
        plan.name = payload.name
    if payload.description is not None:
        plan.description = payload.description
    if payload.sort_order is not None:
        plan.sort_order = payload.sort_order
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A plan with this name already exists") from exc
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}")
def delete_budget_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    plan = db.query(models.BudgetPlan).filter_by(id=plan_id, client_id=current_client.id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Budget plan not found")
    if plan.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default plan")

    # Soft-delete all lines belonging to this plan
    (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == current_client.id,
            models.MonthlyPlanLine.plan_id == plan_id,
        )
        .update({"is_active": False})
    )
    db.delete(plan)
    db.commit()
    return {"message": "Budget plan deleted"}
