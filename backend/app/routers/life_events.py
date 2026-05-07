from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime
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
from ..services.budget_plan_service import get_budget_summary as build_budget_summary, save_plan_lines

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
    roadmap_interval: str = Query("auto", description="Roadmap granularity: auto|monthly|quarterly|annual"),
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
        roadmap_interval=roadmap_interval,
    )

@router.get("/budget-summary")
def get_budget_summary(
    period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    cash_flow_start_period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    cash_flow_months: int = Query(12, ge=1, le=36),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get monthly cash-flow plan summary."""
    if not period:
        period = datetime.now().strftime("%Y-%m")
    return build_budget_summary(
        db,
        current_client.id,
        period,
        cash_flow_start_period=cash_flow_start_period,
        cash_flow_months=cash_flow_months,
    )


@router.get("/monthly-plan-lines")
def get_monthly_plan_lines(
    period: Optional[str] = Query(None, description="Format: YYYY-MM"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not period:
        period = datetime.now().strftime("%Y-%m")
    return build_budget_summary(db, current_client.id, period)["plan_lines"]


@router.post("/monthly-plan-lines/batch")
def save_monthly_plan_lines(
    lines: List[schemas.MonthlyPlanLineCreate],
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    saved = save_plan_lines(db, current_client.id, lines)
    return {"status": "success", "ids": [line.id for line in saved]}


@router.delete("/monthly-plan-lines/{line_id}")
def delete_monthly_plan_line(
    line_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    line = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.id == line_id,
        models.MonthlyPlanLine.client_id == current_client.id,
    ).first()
    if not line:
        raise HTTPException(status_code=404, detail="Monthly plan line not found")
    line.is_active = False
    db.commit()
    return {"message": "Monthly plan line deleted"}

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


