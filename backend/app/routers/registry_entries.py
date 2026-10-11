from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.registry_service import create_entry, delete_entry, list_entries, update_entry


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


@router.get("/", response_model=List[schemas.RegistryEntry])
def get_registry_entries(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    entries = list_entries(db, current_client.id)
    return [enrich_entry(entry) for entry in entries]


@router.post("/", response_model=schemas.RegistryEntry)
def create_registry_entry(
    payload: schemas.RegistryEntryCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    entry = create_entry(db, current_client.id, payload.model_dump())
    invalidate_client(current_client.id)
    return enrich_entry(entry)


@router.put("/{entry_id}", response_model=schemas.RegistryEntry)
def update_registry_entry(
    entry_id: int,
    payload: schemas.RegistryEntryCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    entry = update_entry(db, current_client.id, entry_id, payload.model_dump())
    if entry is None:
        raise HTTPException(status_code=404, detail="Registry entry not found")
    invalidate_client(current_client.id)
    return enrich_entry(entry)


@router.delete("/{entry_id}", status_code=204)
def delete_registry_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not delete_entry(db, current_client.id, entry_id):
        raise HTTPException(status_code=404, detail="Registry entry not found")
    invalidate_client(current_client.id)
