from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import date, datetime
import json
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.goal_service import (
    get_life_events_with_progress, 
    calculate_overall_goal_probability, 
    generate_budget_from_goals,
    get_strategy_dashboard
)
from ..services.capsule_service import create_capsule_for_goal, capsule_balance
from ..services.accounting_service import process_transaction
from ..services.fx_service import calculate_account_valued_balance, convert_transaction_amount

router = APIRouter(prefix="/life-events", tags=["life_events"])


def _parse_contribution_schedule(raw: Optional[str]) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid contribution_schedule JSON") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="contribution_schedule must be a list")
    return [item for item in value if isinstance(item, dict)]

@router.get("/")
def get_life_events(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all life events for current client."""
    return db.query(models.LifeEvent).filter(models.LifeEvent.client_id == current_client.id).all()

@router.get("/with-progress")
def get_life_events_progress(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all life events with calculated progress for current client."""
    return get_life_events_with_progress(db, client_id=current_client.id)

@router.get("/goal-probability")
def get_goal_probability(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get overall goal probability calculation for current client."""
    return calculate_overall_goal_probability(db, client_id=current_client.id)

@router.get("/dashboard")
def get_dashboard(
    annual_return: float = Query(5.0, description="Annual return rate (%)"),
    inflation: float = Query(2.0, description="Inflation rate (%)"),
    monthly_savings: float = Query(50000.0, description="Monthly savings amount"),
    contribution_schedule: Optional[str] = Query(None, description="JSON contribution schedule"),
    allocation_mode: str = Query("weighted", pattern="^(weighted|direct)$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get comprehensive strategy dashboard with events, projections, and unallocated assets."""
    return get_strategy_dashboard(
        db, 
        client_id=current_client.id,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=_parse_contribution_schedule(contribution_schedule),
        allocation_mode=allocation_mode,
    )

@router.get("/budget-summary")
def get_budget_summary(
    period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get budget summary: required savings from goals + fixed costs from recurring."""
    if not period:
        period = datetime.now().strftime("%Y-%m")
    year, month = [int(part) for part in period.split("-")]
    period_start = date(year, month, 1)
    period_end = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
    
    # Calculate required monthly savings from life event gaps
    events_with_progress = get_life_events_with_progress(db, client_id=current_client.id)
    total_gap = sum(max(0, e["gap"]) for e in events_with_progress)
    avg_years = sum(e["years_remaining"] for e in events_with_progress) / len(events_with_progress) if events_with_progress else 10
    required_monthly_savings = total_gap / (avg_years * 12) if avg_years > 0 else 0
    
    # Get fixed costs from recurring transactions (expense type)
    recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == current_client.id,
        models.RecurringTransaction.is_active == True,
        models.RecurringTransaction.type.in_([
            "Expense",
            "expense",
            "CreditExpense",
            "creditexpense",
            "LiabilityPayment",
            "liabilitypayment",
        ])
    ).all()
    
    monthly_fixed_costs = 0.0
    for rec in recurring:
        if rec.frequency == "Monthly":
            monthly_fixed_costs += rec.amount
        elif rec.frequency == "Yearly":
            monthly_fixed_costs += rec.amount / 12
    
    # Get all expense accounts
    expense_accounts = db.query(models.Account).filter(
        models.Account.client_id == current_client.id,
        models.Account.account_type == "expense",
        models.Account.is_active == True
    ).all()
    
    # Fetch monthly budgets for this period
    monthly_budgets = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.client_id == current_client.id,
        models.MonthlyBudget.target_period == period
    ).all()
    budget_map = {mb.account_id: mb.amount for mb in monthly_budgets}
    
    expense_budgets = []
    total_variable_budget = 0.0
    
    for acc in expense_accounts:
        amount = budget_map.get(acc.id, 0.0)

        expense_budgets.append({
            "id": acc.id,
            "name": acc.name,
            "amount": amount,
            "balance": calculate_account_valued_balance(db, acc),
            "is_custom": acc.id in budget_map
        })
        total_variable_budget += amount

    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == current_client.id
    ).all()
    capsule_account_ids = [capsule.account_id for capsule in capsules if capsule.account_id]
    actual_by_capsule_account: dict[int, float] = {account_id: 0.0 for account_id in capsule_account_ids}
    if capsule_account_ids:
        capsule_transactions = db.query(models.Transaction).filter(
            models.Transaction.client_id == current_client.id,
            models.Transaction.type == "Transfer",
            models.Transaction.to_account_id.in_(capsule_account_ids),
            models.Transaction.date >= period_start,
            models.Transaction.date < period_end,
        ).all()
        for tx in capsule_transactions:
            actual_by_capsule_account[tx.to_account_id] = actual_by_capsule_account.get(tx.to_account_id, 0.0) + convert_transaction_amount(db, tx, current_client.id)

    sinking_funds = []
    total_capsule_plan = 0.0
    total_capsule_actual = 0.0
    for capsule in capsules:
        planned = capsule.monthly_contribution or 0.0
        actual = actual_by_capsule_account.get(capsule.account_id, 0.0) if capsule.account_id else 0.0
        total_capsule_plan += planned
        total_capsule_actual += actual
        sinking_funds.append({
            "id": capsule.id,
            "name": capsule.name,
            "life_event_id": capsule.life_event_id,
            "account_id": capsule.account_id,
            "planned": round(planned, 0),
            "actual": round(actual, 0),
            "variance": round(planned - actual, 0),
            "current_balance": round(capsule.current_balance or 0.0, 0),
            "target_amount": round(capsule.target_amount or 0.0, 0),
        })
    
    # Get total income from income accounts or recurring
    income_recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == current_client.id,
        models.RecurringTransaction.is_active == True,
        models.RecurringTransaction.type.in_(["Income", "income"])
    ).all()
    
    monthly_income = sum(r.amount for r in income_recurring if r.frequency == "Monthly")
    monthly_income += sum(r.amount / 12 for r in income_recurring if r.frequency == "Yearly")
    
    remaining = monthly_income - required_monthly_savings - monthly_fixed_costs - total_variable_budget - total_capsule_plan
    
    return {
        "period": period,
        "required_monthly_savings": round(required_monthly_savings, 0),
        "monthly_fixed_costs": round(monthly_fixed_costs, 0),
        "monthly_income": round(monthly_income, 0),
        "total_variable_budget": round(total_variable_budget, 0),
        "total_capsule_plan": round(total_capsule_plan, 0),
        "total_capsule_actual": round(total_capsule_actual, 0),
        "remaining_balance": round(remaining, 0),
        "expense_accounts": expense_budgets,
        "sinking_funds": sinking_funds,
        "goals_count": len(events_with_progress),
        "total_goal_gap": round(total_gap, 0)
    }

@router.post("/monthly-budget")
def save_monthly_budget(
    budget_data: schemas.MonthlyBudgetCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Save or update a monthly budget for a specific account and period."""
    db_budget = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.account_id == budget_data.account_id,
        models.MonthlyBudget.target_period == budget_data.target_period,
        models.MonthlyBudget.client_id == current_client.id
    ).first()
    
    if db_budget:
        db_budget.amount = budget_data.amount
    else:
        db_budget = models.MonthlyBudget(
            **budget_data.model_dump(),
            client_id=current_client.id
        )
        db.add(db_budget)
    
    db.commit()
    return {"status": "success"}

@router.post("/monthly-budget/batch")
def save_batch_monthly_budgets(
    budgets: List[schemas.MonthlyBudgetCreate],
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Save/update multiple monthly budgets."""
    for b in budgets:
        db_budget = db.query(models.MonthlyBudget).filter(
            models.MonthlyBudget.account_id == b.account_id,
            models.MonthlyBudget.target_period == b.target_period,
            models.MonthlyBudget.client_id == current_client.id
        ).first()
        
        if db_budget:
            db_budget.amount = b.amount
        else:
            db_budget = models.MonthlyBudget(
                **b.model_dump(),
                client_id=current_client.id
            )
            db.add(db_budget)
            
    db.commit()
    return {"status": "success"}

@router.post("/")
def create_life_event(
    life_event: schemas.LifeEventCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create a new life event for current client."""
    db_event = models.LifeEvent(**life_event.model_dump(), client_id=current_client.id)
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    from ..services.milestone_service import reset_milestones_from_annual_plan

    reset_milestones_from_annual_plan(db, current_client.id, db_event.id)
    create_capsule_for_goal(db, current_client.id, db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@router.put("/{event_id}")
def update_life_event(
    event_id: int, 
    life_event: schemas.LifeEventUpdate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Update a life event belonging to current client."""
    db_event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == event_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    
    if not db_event:
        raise HTTPException(status_code=404, detail="Life event not found")
        
    for key, value in life_event.model_dump(exclude_unset=True).items():
        setattr(db_event, key, value)
    db.commit()
    db.refresh(db_event)
    return db_event

@router.get("/{event_id}/capsules")
def get_capsules_for_goal(
    event_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Return capsules linked to this goal with their current balances."""
    db_event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == event_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Life event not found")

    result = []
    for cap in db_event.capsules:
        bal = capsule_balance(db, cap)
        result.append({
            "id": cap.id,
            "name": cap.name,
            "current_balance": bal,
            "account_id": cap.account_id,
        })
    return result


@router.delete("/{event_id}")
def delete_life_event(
    event_id: int,
    transfer_account_id: Optional[int] = Query(None, description="Transfer capsule balances to this account before deletion"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Delete a life event belonging to current client.

    If any linked Capsule has a non-zero balance, transfer_account_id is required.
    Each Capsule's balance is moved to transfer_account_id via a Transfer transaction
    before the Goal (and all its Capsules, CapsuleRules, Allocations, Milestones) is deleted.
    The earmarked Account created for each Capsule is also deleted.
    """
    db_event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == event_id,
        models.LifeEvent.client_id == current_client.id
    ).first()

    if not db_event:
        raise HTTPException(status_code=404, detail="Life event not found")

    # Validate transfer_account_id when capsules have a positive balance
    capsules_with_balance = [
        c for c in db_event.capsules
        if c.account_id is not None and capsule_balance(db, c) > 0
    ]
    if capsules_with_balance and transfer_account_id is None:
        raise HTTPException(
            status_code=422,
            detail="transfer_account_id is required because one or more capsules have a non-zero balance."
        )

    if transfer_account_id is not None:
        dest_account = db.get(models.Account, transfer_account_id)
        if not dest_account or dest_account.client_id != current_client.id:
            raise HTTPException(status_code=404, detail="Transfer destination account not found")

    # Transfer each capsule's balance to the destination account
    from datetime import date as _date
    for cap in capsules_with_balance:
        bal = capsule_balance(db, cap)
        tx = models.Transaction(
            client_id=current_client.id,
            date=_date.today(),
            description=f"Goal deleted – funds returned from Capsule: {cap.name}",
            amount=bal,
            type="Transfer",
            from_account_id=cap.account_id,
            to_account_id=transfer_account_id,
            currency="JPY",
            category="capsule_return",
        )
        db.add(tx)
        db.flush()
        process_transaction(db, tx)

    # Collect capsule account IDs before cascade deletion
    account_ids_to_delete = [
        c.account_id for c in db_event.capsules if c.account_id is not None
    ]

    # Nullify account_id on capsules so accounts can be deleted without FK violation
    for cap in db_event.capsules:
        cap.account_id = None
    db.flush()

    # Delete the life event (cascades: capsules, capsule_rules, goal_allocations, milestones)
    db.delete(db_event)
    db.flush()

    # Delete the (now-empty) earmarked accounts that belonged to capsules
    for account_id in account_ids_to_delete:
        account = db.get(models.Account, account_id)
        if account:
            db.query(models.JournalEntry).filter(
                models.JournalEntry.account_id == account_id
            ).delete(synchronize_session=False)
            db.delete(account)

    db.commit()
    return {"message": "Deleted"}

@router.get("/generate-budget/{month}")
def generate_budget(
    month: str, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Generate budget template from life event goals for current client."""
    return generate_budget_from_goals(db, month, client_id=current_client.id)

# ========== Allocations ==========

@router.get("/{event_id}/allocations")
def get_allocations(
    event_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all allocations for a life event."""
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == event_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")
    
    result = []
    for alloc in event.allocations:
        result.append({
            "id": alloc.id,
            "life_event_id": alloc.life_event_id,
            "account_id": alloc.account_id,
            "allocation_percentage": alloc.allocation_percentage,
            "account_name": alloc.account.name if alloc.account else None,
            "account_balance": calculate_account_valued_balance(db, alloc.account) if alloc.account else 0
        })
    return result

@router.post("/{event_id}/allocations")
def add_allocation(
    event_id: int,
    allocation: schemas.GoalAllocationCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Add an asset allocation to a life event."""
    # Verify event exists and belongs to client
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == event_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")
    
    # Verify account exists for this client and is an asset
    account = db.query(models.Account).filter(
        models.Account.id == allocation.account_id,
        models.Account.client_id == current_client.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.account_type != "asset":
        raise HTTPException(status_code=400, detail="Only asset accounts can be allocated to goals")

    existing_same_goal = db.query(models.GoalAllocation).filter(
        models.GoalAllocation.life_event_id == event_id,
        models.GoalAllocation.account_id == allocation.account_id
    ).first()
    if existing_same_goal:
        raise HTTPException(status_code=400, detail="Asset is already allocated to this goal")
    
    # Validation: Ensure total allocation for this account across ALL goals does not exceed 100%
    # 1. Sum existing allocations for this account
    existing_allocations = db.query(models.GoalAllocation).join(models.LifeEvent).filter(
        models.GoalAllocation.account_id == allocation.account_id,
        models.LifeEvent.client_id == current_client.id
    ).all()
    current_total = sum(a.allocation_percentage for a in existing_allocations)
    
    if current_total + allocation.allocation_percentage > 100.0:
        remaining = 100.0 - current_total
        raise HTTPException(
            status_code=400, 
            detail=f"Asset is over-allocated. Current total: {current_total}%. Remaining: {remaining}%. Requested: {allocation.allocation_percentage}%"
        )
    
    db_alloc = models.GoalAllocation(
        life_event_id=event_id,
        account_id=allocation.account_id,
        allocation_percentage=allocation.allocation_percentage
    )
    db.add(db_alloc)
    db.commit()
    db.refresh(db_alloc)
    
    return {
        "id": db_alloc.id,
        "life_event_id": db_alloc.life_event_id,
        "account_id": db_alloc.account_id,
        "allocation_percentage": db_alloc.allocation_percentage,
        "account_name": account.name,
        "account_balance": calculate_account_valued_balance(db, account)
    }

@router.put("/allocations/{allocation_id}")
def update_allocation(
    allocation_id: int,
    allocation: schemas.GoalAllocationCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Update an allocation percentage."""
    db_alloc = db.query(models.GoalAllocation).join(models.LifeEvent).filter(
        models.GoalAllocation.id == allocation_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    if not db_alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")
    
    account = db.query(models.Account).filter(
        models.Account.id == allocation.account_id,
        models.Account.client_id == current_client.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.account_type != "asset":
        raise HTTPException(status_code=400, detail="Only asset accounts can be allocated to goals")

    existing_same_goal = db.query(models.GoalAllocation).filter(
        models.GoalAllocation.life_event_id == db_alloc.life_event_id,
        models.GoalAllocation.account_id == allocation.account_id,
        models.GoalAllocation.id != allocation_id
    ).first()
    if existing_same_goal:
        raise HTTPException(status_code=400, detail="Asset is already allocated to this goal")

    # Validation: Ensure total allocation for this account (excluding current record) + new value <= 100%
    other_allocations = db.query(models.GoalAllocation).join(models.LifeEvent).filter(
        models.GoalAllocation.account_id == allocation.account_id,
        models.GoalAllocation.id != allocation_id,
        models.LifeEvent.client_id == current_client.id
    ).all()
    
    current_total_others = sum(a.allocation_percentage for a in other_allocations)
    
    if current_total_others + allocation.allocation_percentage > 100.0:
         remaining = 100.0 - current_total_others
         raise HTTPException(
            status_code=400,
            detail=f"Asset is over-allocated. Total others: {current_total_others}%. Remaining: {remaining}%. Requested: {allocation.allocation_percentage}%"
        )
    
    db_alloc.account_id = allocation.account_id
    db_alloc.allocation_percentage = allocation.allocation_percentage
    db.commit()
    db.refresh(db_alloc)
    
    return {
        "id": db_alloc.id,
        "life_event_id": db_alloc.life_event_id,
        "account_id": db_alloc.account_id,
        "allocation_percentage": db_alloc.allocation_percentage,
        "account_name": account.name,
        "account_balance": calculate_account_valued_balance(db, account)
    }

@router.delete("/allocations/{allocation_id}")
def delete_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Remove an allocation."""
    db_alloc = db.query(models.GoalAllocation).join(models.LifeEvent).filter(
        models.GoalAllocation.id == allocation_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    if not db_alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")
    
    db.delete(db_alloc)
    db.commit()
    return {"message": "Allocation removed"}
