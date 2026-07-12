from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date
from typing import List
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.registry_service import detach_registry_from_recurring, sync_registry_from_recurring
from ..services.recurring_service import (
    advance_next_due_date,
    ensure_next_due_date,
    is_past_end_period,
    post_recurring_transaction,
    process_due_for_client,
)

router = APIRouter(prefix="/recurring", tags=["recurring"])


@router.get("/", response_model=List[schemas.RecurringTransaction])
def get_recurring_transactions(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    rows = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == current_client.id
    ).all()
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
    db_recurring = models.RecurringTransaction(
        **recurring.model_dump(),
        client_id=current_client.id
    )
    db.add(db_recurring)
    db.flush()
    ensure_next_due_date(db_recurring, date.today())
    # Registry is the source of truth: link to (or create) the matching registry entry.
    sync_registry_from_recurring(db, db_recurring)
    db.commit()
    db.refresh(db_recurring)
    invalidate_client(current_client.id)
    return db_recurring

@router.put("/{recurring_id}", response_model=schemas.RecurringTransaction)
def update_recurring_transaction(
    recurring_id: int,
    recurring_update: schemas.RecurringTransactionCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == current_client.id
    ).first()
    
    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    update_data = recurring_update.model_dump(exclude_unset=True)
    explicit_next_due = "next_due_date" in recurring_update.model_fields_set
    schedule_fields = {"frequency", "day_of_month", "month_of_year", "start_period"}
    schedule_changed = any(
        key in update_data and getattr(db_recurring, key) != update_data[key]
        for key in schedule_fields
    )
    for key, value in update_data.items():
        setattr(db_recurring, key, value)
    if schedule_changed and not explicit_next_due:
        db_recurring.next_due_date = None
    ensure_next_due_date(db_recurring, date.today())

    sync_registry_from_recurring(db, db_recurring)
    db.commit()
    db.refresh(db_recurring)
    invalidate_client(current_client.id)
    return db_recurring


@router.patch("/{recurring_id}", response_model=schemas.RecurringTransaction)
def patch_recurring_transaction(
    recurring_id: int,
    recurring_update: schemas.RecurringTransactionUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == current_client.id
    ).first()

    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    update_data = recurring_update.model_dump(exclude_unset=True)
    explicit_next_due = "next_due_date" in recurring_update.model_fields_set
    schedule_fields = {"frequency", "day_of_month", "month_of_year", "start_period"}
    schedule_changed = any(
        key in update_data and getattr(db_recurring, key) != update_data[key]
        for key in schedule_fields
    )
    for key, value in update_data.items():
        setattr(db_recurring, key, value)
    if schedule_changed and not explicit_next_due:
        db_recurring.next_due_date = None
    ensure_next_due_date(db_recurring, date.today())

    sync_registry_from_recurring(db, db_recurring)
    db.commit()
    db.refresh(db_recurring)
    invalidate_client(current_client.id)
    return db_recurring


@router.delete("/{recurring_id}")
def delete_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == current_client.id
    ).first()
    
    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    detach_registry_from_recurring(db, db_recurring)
    db.delete(db_recurring)
    db.commit()
    invalidate_client(current_client.id)
    return {"message": "Recurring transaction deleted"}

@router.get("/due", response_model=List[schemas.RecurringTransaction])
def get_due_recurring_transactions(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    today = date.today()
    return db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == current_client.id,
        models.RecurringTransaction.is_active == True,
        models.RecurringTransaction.next_due_date <= today
    ).all()


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
    db_recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == current_client.id
    ).first()
    
    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")
    if not db_recurring.is_active:
        raise HTTPException(status_code=409, detail="Recurring transaction is inactive")

    posting_date = db_recurring.next_due_date or date.today()
    if is_past_end_period(db_recurring, posting_date):
        raise HTTPException(status_code=409, detail="Recurring transaction is past its end period")

    if db_recurring.next_due_date is None:
        db_recurring.next_due_date = posting_date
    try:
        db_transaction = post_recurring_transaction(db, db_recurring, posting_date)
        advance_next_due_date(db_recurring)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_recurring)
    invalidate_client(current_client.id)

    return {"message": "Transaction processed", "transaction_id": db_transaction.id, "next_due_date": db_recurring.next_due_date}


@router.post("/{recurring_id}/skip")
def skip_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == current_client.id
    ).first()

    if not db_recurring:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    advance_next_due_date(db_recurring)
    db.commit()
    db.refresh(db_recurring)
    invalidate_client(current_client.id)

    return {"message": "Recurring transaction skipped", "next_due_date": db_recurring.next_due_date}
