from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client

router = APIRouter(prefix="/budgets", tags=["budgets"])


class BudgetLimitUpdate(BaseModel):
    budget_limit: Optional[float] = None


def _period_to_range(period: str) -> tuple[date, date]:
    year, month = map(int, period.split("-"))
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


@router.get("/", response_model=List[schemas.MonthlyBudgetWithAccount])
def get_budgets(
    period: Optional[str] = Query(None, description="YYYY-MM"),
    month: Optional[str] = Query(None, description="Backward compatibility alias"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not period:
        period = month
    if not period:
        today = date.today()
        period = f"{today.year}-{today.month:02d}"

    start_date, end_date = _period_to_range(period)

    budgets = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.client_id == current_client.id,
        models.MonthlyBudget.target_period == period,
    ).all()

    accounts = db.query(models.Account).filter(
        models.Account.client_id == current_client.id,
    ).all()
    account_map = {a.id: a for a in accounts}
    account_name_to_id = {a.name: a.id for a in accounts}

    expense_txs = db.query(models.Transaction).filter(
        and_(
            models.Transaction.client_id == current_client.id,
            models.Transaction.date >= start_date,
            models.Transaction.date < end_date,
            models.Transaction.type.in_(["Expense", "LiabilityPayment"]),
        )
    ).all()

    actual_map: dict[int, float] = {}
    for tx in expense_txs:
        if tx.to_account_id and tx.to_account_id in account_map:
            actual_map[tx.to_account_id] = actual_map.get(tx.to_account_id, 0.0) + tx.amount
            continue
        if tx.category and tx.category in account_name_to_id:
            acc_id = account_name_to_id[tx.category]
            actual_map[acc_id] = actual_map.get(acc_id, 0.0) + tx.amount

    result = []
    for budget in budgets:
        acc = account_map.get(budget.account_id)
        actual = actual_map.get(budget.account_id, 0.0)
        result.append(
            {
                "id": budget.id,
                "account_id": budget.account_id,
                "target_period": budget.target_period,
                "amount": budget.amount,
                "account_name": acc.name if acc else "Unknown",
                "account_type": acc.account_type if acc else "unknown",
                "actual_spending": round(actual, 2),
                "variance": round(budget.amount - actual, 2),
            }
        )
    return result


@router.post("/", response_model=schemas.MonthlyBudget)
def upsert_budget(
    budget: schemas.MonthlyBudgetCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    account = db.query(models.Account).filter(
        models.Account.id == budget.account_id,
        models.Account.client_id == current_client.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    existing = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.client_id == current_client.id,
        models.MonthlyBudget.account_id == budget.account_id,
        models.MonthlyBudget.target_period == budget.target_period,
    ).first()

    if existing:
        existing.amount = budget.amount
        db.commit()
        db.refresh(existing)
        return existing

    db_budget = models.MonthlyBudget(
        **budget.model_dump(),
        client_id=current_client.id,
    )
    db.add(db_budget)
    db.commit()
    db.refresh(db_budget)
    return db_budget


@router.delete("/{budget_id}")
def delete_budget(
    budget_id: str,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    budget = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.id == budget_id,
        models.MonthlyBudget.client_id == current_client.id,
    ).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    db.delete(budget)
    db.commit()
    return {"message": "Budget deleted"}


@router.get("/defaults")
def get_budget_defaults(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    accounts = db.query(models.Account).filter(
        models.Account.client_id == current_client.id,
        models.Account.account_type == "expense",
        models.Account.is_active.is_(True),
    ).all()
    return [
        {
            "account_id": a.id,
            "account_name": a.name,
            "budget_limit": a.budget_limit,
        }
        for a in accounts
    ]


@router.put("/defaults/{account_id}")
def update_budget_default(
    account_id: int,
    payload: BudgetLimitUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == current_client.id,
        models.Account.account_type == "expense",
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Expense account not found")

    account.budget_limit = payload.budget_limit
    db.commit()
    db.refresh(account)
    return {
        "account_id": account.id,
        "account_name": account.name,
        "budget_limit": account.budget_limit,
    }
