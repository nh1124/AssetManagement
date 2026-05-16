from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.registry_service import ensure_registry_entries


router = APIRouter(prefix="/registry-entries", tags=["registry-entries"])


def enrich_entry(entry: models.RegistryEntry) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "entry_type": entry.entry_type,
        "category": entry.category,
        "amount": entry.amount,
        "currency": entry.currency,
        "frequency": entry.frequency,
        "frequency_days": entry.frequency_days,
        "day_of_month": entry.day_of_month,
        "month_of_year": entry.month_of_year,
        "transaction_type": entry.transaction_type,
        "line_type": entry.line_type,
        "budget_account_id": entry.budget_account_id,
        "budget_account_name": entry.budget_account.name if entry.budget_account else None,
        "source_account_id": entry.source_account_id,
        "source_account_name": entry.source_account.name if entry.source_account else None,
        "destination_account_id": entry.destination_account_id,
        "destination_account_name": entry.destination_account.name if entry.destination_account else None,
        "funding_capsule_id": entry.funding_capsule_id,
        "funding_capsule_name": entry.funding_capsule.name if entry.funding_capsule else None,
        "budget_treatment": entry.budget_treatment,
        "generate_recurring": entry.generate_recurring,
        "budget_active": entry.budget_active,
        "is_active": entry.is_active,
        "source_product_id": entry.source_product_id,
        "source_recurring_transaction_id": entry.source_recurring_transaction_id,
        "recurring_transaction_id": entry.source_recurring_transaction_id,
        "note": entry.note,
        "start_period": entry.start_period,
        "end_period": entry.end_period,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def validate_accounts(db: Session, client_id: int, data: dict) -> None:
    for key in ("budget_account_id", "source_account_id", "destination_account_id"):
        account_id = data.get(key)
        if account_id is None:
            continue
        account = db.query(models.Account).filter(
            models.Account.id == account_id,
            models.Account.client_id == client_id,
        ).first()
        if not account:
            raise HTTPException(status_code=400, detail=f"{key} must belong to this client")


def registry_to_recurring_data(entry: models.RegistryEntry) -> dict:
    return {
        "name": entry.name,
        "amount": entry.amount or 0.0,
        "currency": entry.currency or "JPY",
        "type": entry.transaction_type or "Expense",
        "from_account_id": entry.source_account_id,
        "to_account_id": entry.destination_account_id or entry.budget_account_id,
        "frequency": entry.frequency if entry.frequency in {"Monthly", "Yearly"} else "Monthly",
        "day_of_month": entry.day_of_month or 1,
        "month_of_year": entry.month_of_year if entry.frequency == "Yearly" else None,
        "start_period": entry.start_period,
        "end_period": entry.end_period,
        "auto_post": True,
        "is_active": entry.is_active,
        "source_registry_entry_id": entry.id,
    }


def sync_recurring_from_registry(db: Session, entry: models.RegistryEntry) -> None:
    if not entry.generate_recurring:
        if entry.source_recurring_transaction_id:
            recurring = db.query(models.RecurringTransaction).filter(
                models.RecurringTransaction.id == entry.source_recurring_transaction_id,
                models.RecurringTransaction.client_id == entry.client_id,
            ).first()
            entry.source_recurring_transaction_id = None
            if recurring:
                db.delete(recurring)
        return
    recurring = None
    if entry.source_recurring_transaction_id:
        recurring = db.query(models.RecurringTransaction).filter(
            models.RecurringTransaction.id == entry.source_recurring_transaction_id,
            models.RecurringTransaction.client_id == entry.client_id,
        ).first()
    if not recurring:
        recurring = models.RecurringTransaction(client_id=entry.client_id)
        db.add(recurring)
        db.flush()
        entry.source_recurring_transaction_id = recurring.id
    for key, value in registry_to_recurring_data(entry).items():
        setattr(recurring, key, value)


@router.get("/", response_model=List[schemas.RegistryEntry])
def get_registry_entries(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    ensure_registry_entries(db, current_client.id)
    entries = db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == current_client.id,
    ).order_by(models.RegistryEntry.entry_type, models.RegistryEntry.name).all()
    return [enrich_entry(entry) for entry in entries]


@router.post("/", response_model=schemas.RegistryEntry)
def create_registry_entry(
    payload: schemas.RegistryEntryCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    data = payload.model_dump()
    validate_accounts(db, current_client.id, data)
    entry = models.RegistryEntry(**data, client_id=current_client.id)
    db.add(entry)
    db.flush()
    sync_recurring_from_registry(db, entry)
    db.commit()
    db.refresh(entry)
    invalidate_client(current_client.id)
    return enrich_entry(entry)


@router.put("/{entry_id}", response_model=schemas.RegistryEntry)
def update_registry_entry(
    entry_id: int,
    payload: schemas.RegistryEntryCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    entry = db.query(models.RegistryEntry).filter(
        models.RegistryEntry.id == entry_id,
        models.RegistryEntry.client_id == current_client.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Registry entry not found")
    data = payload.model_dump()
    validate_accounts(db, current_client.id, data)
    for key, value in data.items():
        setattr(entry, key, value)
    sync_recurring_from_registry(db, entry)
    db.commit()
    db.refresh(entry)
    invalidate_client(current_client.id)
    return enrich_entry(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_registry_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    entry = db.query(models.RegistryEntry).filter(
        models.RegistryEntry.id == entry_id,
        models.RegistryEntry.client_id == current_client.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Registry entry not found")
    if entry.source_recurring_transaction_id:
        recurring = db.query(models.RecurringTransaction).filter(
            models.RecurringTransaction.id == entry.source_recurring_transaction_id,
            models.RecurringTransaction.client_id == current_client.id,
        ).first()
        entry.source_recurring_transaction_id = None
        if recurring:
            db.delete(recurring)
    entry.is_active = False
    entry.budget_active = False
    entry.generate_recurring = False
    db.commit()
    invalidate_client(current_client.id)
