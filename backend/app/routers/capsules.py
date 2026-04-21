from __future__ import annotations

import re
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import database, dependencies, models, schemas
from ..services.accounting_service import get_or_create_account, process_transaction

router = APIRouter(
    prefix="/capsules",
    tags=["Capsules"],
    dependencies=[Depends(dependencies.get_current_client)],
)


class CapsuleContributionRequest(BaseModel):
    amount: float
    from_account_id: int
    contribution_date: Optional[date] = None


def _slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _capsule_to_dict(capsule: models.Capsule) -> dict:
    balance = capsule.account.balance if capsule.account else capsule.current_balance
    progress_pct = (balance / capsule.target_amount * 100) if capsule.target_amount else 0
    return {
        "id": capsule.id,
        "name": capsule.name,
        "target_amount": capsule.target_amount,
        "monthly_contribution": capsule.monthly_contribution,
        "current_balance": balance,
        "account_id": capsule.account_id,
        "created_at": capsule.created_at,
        "progress_pct": round(progress_pct, 1),
    }


def _create_capsule_account(db: Session, client_id: int, capsule_name: str) -> models.Account:
    base = f"capsule_{_slug(capsule_name)}"
    candidate = base
    i = 2
    while db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.name == candidate,
    ).first():
        candidate = f"{base}_{i}"
        i += 1

    account = models.Account(
        client_id=client_id,
        name=candidate,
        account_type="asset",
        balance=0.0,
    )
    db.add(account)
    db.flush()
    return account


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
    return [_capsule_to_dict(c) for c in capsules]


@router.post("/", response_model=schemas.Capsule)
def create_capsule(
    capsule: schemas.CapsuleCreate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    account = _create_capsule_account(db, current_client.id, capsule.name)
    db_capsule = models.Capsule(
        client_id=current_client.id,
        name=capsule.name,
        target_amount=capsule.target_amount,
        monthly_contribution=capsule.monthly_contribution,
        current_balance=0.0,
        account_id=account.id,
    )
    db.add(db_capsule)
    db.commit()
    db.refresh(db_capsule)
    return _capsule_to_dict(db_capsule)


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
            # Keep account balance as source of truth.
            if db_capsule.account:
                db_capsule.account.balance = value or 0.0
            db_capsule.current_balance = value or 0.0
        else:
            setattr(db_capsule, key, value)

    db.commit()
    db.refresh(db_capsule)
    return _capsule_to_dict(db_capsule)


@router.delete("/{capsule_id}")
def delete_capsule(
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
    if not capsule or not capsule.account_id:
        raise HTTPException(status_code=404, detail="Capsule not found")

    from_account = db.query(models.Account).filter(
        models.Account.id == payload.from_account_id,
        models.Account.client_id == current_client.id,
    ).first()
    if not from_account:
        raise HTTPException(status_code=404, detail="Source account not found")

    tx = models.Transaction(
        client_id=current_client.id,
        date=payload.contribution_date or date.today(),
        description=f"Capsule contribution: {capsule.name}",
        amount=payload.amount,
        type="Transfer",
        from_account_id=from_account.id,
        to_account_id=capsule.account_id,
        from_account=from_account.name,
        to_account=capsule.account.name if capsule.account else None,
        currency="JPY",
        category="capsule_contribution",
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    process_transaction(db, tx)
    db.refresh(capsule)

    return {
        "status": "ok",
        "transaction_id": tx.id,
        "new_balance": capsule.account.balance if capsule.account else capsule.current_balance,
    }


@router.post("/process_contributions")
def process_monthly_contributions(
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == current_client.id
    ).all()
    cash_account = get_or_create_account(db, "cash", current_client.id, "asset")

    total_added = 0.0
    updated_count = 0
    for capsule in capsules:
        if capsule.monthly_contribution <= 0 or not capsule.account_id:
            continue
        tx = models.Transaction(
            client_id=current_client.id,
            date=date.today(),
            description=f"Capsule auto contribution: {capsule.name}",
            amount=capsule.monthly_contribution,
            type="Transfer",
            from_account_id=cash_account.id,
            to_account_id=capsule.account_id,
            from_account=cash_account.name,
            to_account=capsule.account.name if capsule.account else None,
            currency="JPY",
            category="capsule_contribution",
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        process_transaction(db, tx)
        total_added += capsule.monthly_contribution
        updated_count += 1

    return {
        "message": f"Processed contributions for {updated_count} capsules",
        "total_added": total_added,
        "updated_capsules": updated_count,
    }
