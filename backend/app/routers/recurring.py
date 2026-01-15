from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.accounting_service import process_transaction

router = APIRouter(prefix="/recurring", tags=["recurring"])

@router.get("/", response_model=List[schemas.RecurringTransaction])
def get_recurring_transactions(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    return db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == current_client.id
    ).all()

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
    db.commit()
    db.refresh(db_recurring)
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
    for key, value in update_data.items():
        setattr(db_recurring, key, value)

    db.commit()
    db.refresh(db_recurring)
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

    db.delete(db_recurring)
    db.commit()
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

    # 1. Create a real record in the transactions table
    # We need to map from_account_id/to_account_id to names if the transactions table uses names
    from_account = db.query(models.Account).filter(models.Account.id == db_recurring.from_account_id).first()
    to_account = db.query(models.Account).filter(models.Account.id == db_recurring.to_account_id).first()
    
    db_transaction = models.Transaction(
        client_id=current_client.id,
        date=date.today(),
        description=db_recurring.name,
        amount=db_recurring.amount,
        type=db_recurring.type,
        from_account=from_account.name if from_account else "cash",
        to_account=to_account.name if to_account else "expense",
        category=db_recurring.name # Use name as category or default
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)

    # Process double-entry bookkeeping
    process_transaction(db, db_transaction)

    # 2. Update the next_due_date of the recurring item
    if db_recurring.frequency == 'Monthly':
        db_recurring.next_due_date += relativedelta(months=1)
    elif db_recurring.frequency == 'Yearly':
        db_recurring.next_due_date += relativedelta(years=1)
    
    db.commit()
    db.refresh(db_recurring)

    return {"message": "Transaction processed", "transaction_id": db_transaction.id, "next_due_date": db_recurring.next_due_date}
