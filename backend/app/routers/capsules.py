from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import database, dependencies, models, schemas
from ..services.capsule_service import (
    capsule_balance,
    capsule_to_dict,
    create_capsule_for_goal,
    remaining_target,
    upsert_capsule_holding,
)

router = APIRouter(
    prefix="/capsules",
    tags=["Capsules"],
    dependencies=[Depends(dependencies.get_current_client)],
)


class CapsuleContributionRequest(BaseModel):
    amount: float
    from_account_id: int
    contribution_date: Optional[date] = None


def _rule_to_dict(rule: models.CapsuleRule) -> dict:
    return {
        "id": rule.id,
        "capsule_id": rule.capsule_id,
        "capsule_name": rule.capsule.name if rule.capsule else None,
        "trigger_type": rule.trigger_type,
        "trigger_category": rule.trigger_category,
        "trigger_description": rule.trigger_description,
        "source_mode": rule.source_mode,
        "source_account_id": rule.source_account_id,
        "source_account_name": rule.source_account.name if rule.source_account else None,
        "amount_type": rule.amount_type,
        "amount_value": rule.amount_value,
        "is_active": rule.is_active,
        "created_at": rule.created_at,
    }


@router.get("/", response_model=List[schemas.Capsule])
def read_capsules(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == current_client.id
    ).offset(skip).limit(limit).all()
    result = [capsule_to_dict(db, c) for c in capsules]
    db.commit()
    return result


@router.post("/", response_model=schemas.Capsule)
def create_capsule(
    capsule: schemas.CapsuleCreate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    target_amount = max(0.0, capsule.target_amount or 0.0)
    db_capsule = models.Capsule(
        client_id=current_client.id,
        life_event_id=capsule.life_event_id,
        name=capsule.name,
        target_amount=target_amount,
        monthly_contribution=max(0.0, capsule.monthly_contribution or 0.0),
        current_balance=0.0,
        account_id=None,
    )
    db.add(db_capsule)
    db.commit()
    db.refresh(db_capsule)
    return capsule_to_dict(db, db_capsule)


@router.put("/{capsule_id}", response_model=schemas.Capsule)
def update_capsule(
    capsule_id: int,
    capsule_update: schemas.CapsuleUpdate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    db_capsule = db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not db_capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")

    update_data = capsule_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "current_balance":
            continue
        elif key == "target_amount":
            db_capsule.target_amount = max(0.0, value or 0.0)
        elif key == "monthly_contribution":
            db_capsule.monthly_contribution = max(0.0, value or 0.0)
        else:
            setattr(db_capsule, key, value)

    db_capsule.current_balance = capsule_balance(db, db_capsule)

    db.commit()
    db.refresh(db_capsule)
    return capsule_to_dict(db, db_capsule)


@router.delete("/{capsule_id}")
def delete_capsule(
    capsule_id: int,
    transfer_account_id: Optional[int] = Query(None, description="Ignored — kept for backwards compatibility"),
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")

    db.delete(capsule)
    db.commit()
    return {"message": "Capsule deleted successfully"}


@router.post("/{capsule_id}/contribute")
def contribute_to_capsule(
    capsule_id: int,
    payload: CapsuleContributionRequest = Body(...),
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")

    from_account = db.query(models.Account).filter(
        models.Account.id == payload.from_account_id,
        models.Account.client_id == current_client.id,
    ).first()
    if not from_account:
        raise HTTPException(status_code=404, detail="Source account not found")

    amount = payload.amount
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Contribution amount must be positive")

    remaining = remaining_target(db, capsule)
    if remaining <= 0:
        return {
            "status": "skipped",
            "message": "Capsule target already reached",
            "amount": 0.0,
            "new_balance": capsule_balance(db, capsule),
        }

    amount = min(amount, remaining)
    upsert_capsule_holding(db, capsule, from_account.id, amount, note="Manual contribution")
    db.commit()

    return {
        "status": "ok",
        "amount": amount,
        "new_balance": capsule_balance(db, capsule),
    }


@router.post("/process_contributions")
def process_monthly_contributions(
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    return {
        "message": "This endpoint is deprecated. Use CapsuleRules for automatic allocation.",
        "updated_capsules": 0,
        "total_added": 0.0,
    }


@router.post("/life-events/{life_event_id}", response_model=schemas.Capsule)
def create_goal_capsule(
    life_event_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    goal = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == current_client.id,
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Life event not found")
    capsule = create_capsule_for_goal(db, current_client.id, goal)
    db.commit()
    db.refresh(capsule)
    return capsule_to_dict(db, capsule)


@router.get("/rules", response_model=List[schemas.CapsuleRule])
def read_capsule_rules(
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    rules = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.client_id == current_client.id
    ).order_by(models.CapsuleRule.id).all()
    return [_rule_to_dict(rule) for rule in rules]


@router.post("/rules", response_model=schemas.CapsuleRule)
def create_capsule_rule(
    payload: schemas.CapsuleRuleCreate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == payload.capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")
    if payload.source_account_id:
        account = db.query(models.Account).filter(
            models.Account.id == payload.source_account_id,
            models.Account.client_id == current_client.id,
        ).first()
        if not account:
            raise HTTPException(status_code=404, detail="Source account not found")
    rule = models.CapsuleRule(**payload.model_dump(), client_id=current_client.id)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_to_dict(rule)


@router.put("/rules/{rule_id}", response_model=schemas.CapsuleRule)
def update_capsule_rule(
    rule_id: int,
    payload: schemas.CapsuleRuleUpdate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    rule = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.id == rule_id,
        models.CapsuleRule.client_id == current_client.id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return _rule_to_dict(rule)


@router.delete("/rules/{rule_id}")
def delete_capsule_rule(
    rule_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    rule = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.id == rule_id,
        models.CapsuleRule.client_id == current_client.id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"message": "Rule deleted"}


def _holding_to_dict(h: models.CapsuleHolding) -> dict:
    return {
        "id": h.id,
        "capsule_id": h.capsule_id,
        "account_id": h.account_id,
        "account_name": h.account.name if h.account else None,
        "held_amount": h.held_amount,
        "note": h.note,
        "updated_at": h.updated_at,
    }


@router.get("/{capsule_id}/holdings")
def read_capsule_holdings(
    capsule_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")
    return [_holding_to_dict(h) for h in capsule.holdings]


@router.post("/{capsule_id}/holdings")
def create_capsule_holding(
    capsule_id: int,
    payload: schemas.CapsuleHoldingCreate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")

    account = db.query(models.Account).filter(
        models.Account.id == payload.account_id,
        models.Account.client_id == current_client.id,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    existing = db.query(models.CapsuleHolding).filter(
        models.CapsuleHolding.capsule_id == capsule_id,
        models.CapsuleHolding.account_id == payload.account_id,
    ).first()
    if existing:
        existing.held_amount = payload.held_amount
        existing.note = payload.note
        db.commit()
        db.refresh(existing)
        return _holding_to_dict(existing)

    h = models.CapsuleHolding(
        capsule_id=capsule_id,
        account_id=payload.account_id,
        held_amount=payload.held_amount,
        note=payload.note,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return _holding_to_dict(h)


@router.put("/{capsule_id}/holdings/{holding_id}")
def update_capsule_holding(
    capsule_id: int,
    holding_id: int,
    payload: schemas.CapsuleHoldingUpdate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")

    h = db.query(models.CapsuleHolding).filter(
        models.CapsuleHolding.id == holding_id,
        models.CapsuleHolding.capsule_id == capsule_id,
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Holding not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(h, key, value)

    db.commit()
    db.refresh(h)
    return _holding_to_dict(h)


@router.delete("/{capsule_id}/holdings/{holding_id}")
def delete_capsule_holding(
    capsule_id: int,
    holding_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == current_client.id,
    ).first()
    if not capsule:
        raise HTTPException(status_code=404, detail="Capsule not found")

    h = db.query(models.CapsuleHolding).filter(
        models.CapsuleHolding.id == holding_id,
        models.CapsuleHolding.capsule_id == capsule_id,
    ).first()
    if not h:
        raise HTTPException(status_code=404, detail="Holding not found")

    db.delete(h)
    db.commit()
    return {"message": "Holding deleted"}
