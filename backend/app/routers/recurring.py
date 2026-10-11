from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.registry_service import delete_recurring, upsert_registry_from_recurring_payload
from ..services.recurring_service import (
    get_for_client,
    list_due,
    list_for_client,
    process_due_for_client,
    process_one,
    skip_one,
)

router = APIRouter(prefix="/recurring", tags=["recurring"])


@router.get("/", response_model=List[schemas.RecurringTransaction])
def get_recurring_transactions(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    rows = list_for_client(db, current_client.id)
    return [
        {
            **{column.name: getattr(row, column.name) for column in models.RecurringTransaction.__table__.columns},
            "source_registry_entry_name": row.source_registry_entry.name if row.source_registry_entry else None,
        }
        for row in rows
    ]

@router.post("/", response_model=schemas.RecurringTransaction)
def create_recurring_transaction(
    recurring: schemas.RecurringTransactionCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = upsert_registry_from_recurring_payload(
        db, current_client.id, recurring.model_dump(), commit=True
    )
    invalidate_client(current_client.id)
    return db_recurring

@router.put("/{recurring_id}", response_model=schemas.RecurringTransaction)
def update_recurring_transaction(
    recurring_id: int,
    recurring_update: schemas.RecurringTransactionCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = get_for_client(db, current_client.id, recurring_id)
    
    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    db_recurring = upsert_registry_from_recurring_payload(
        db, current_client.id, recurring_update.model_dump(exclude_unset=True), db_recurring,
        commit=True,
    )
    invalidate_client(current_client.id)
    return db_recurring


@router.patch("/{recurring_id}", response_model=schemas.RecurringTransaction)
def patch_recurring_transaction(
    recurring_id: int,
    recurring_update: schemas.RecurringTransactionUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = get_for_client(db, current_client.id, recurring_id)

    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    db_recurring = upsert_registry_from_recurring_payload(
        db, current_client.id, recurring_update.model_dump(exclude_unset=True), db_recurring,
        commit=True,
    )
    invalidate_client(current_client.id)
    return db_recurring


@router.delete("/{recurring_id}")
def delete_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = get_for_client(db, current_client.id, recurring_id)
    
    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    delete_recurring(db, db_recurring)
    invalidate_client(current_client.id)
    return {"message": "Recurring transaction deleted"}

@router.get("/due", response_model=List[schemas.RecurringTransaction])
def get_due_recurring_transactions(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    return list_due(db, current_client.id)


@router.post("/process-due")
def process_due_recurring_transactions(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return process_due_for_client(db, current_client.id)

@router.post("/{recurring_id}/process")
def process_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = get_for_client(db, current_client.id, recurring_id)
    
    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")
    db_transaction, next_due_date = process_one(db, db_recurring)
    invalidate_client(current_client.id)

    return {"message": "Transaction processed", "transaction_id": db_transaction.id, "next_due_date": next_due_date}


@router.post("/{recurring_id}/skip")
def skip_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = get_for_client(db, current_client.id, recurring_id)

    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    next_due_date = skip_one(db, db_recurring)
    invalidate_client(current_client.id)

    return {"message": "Recurring transaction skipped", "next_due_date": next_due_date}
