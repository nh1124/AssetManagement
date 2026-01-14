from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from ..services.accounting_service import process_transaction, ensure_default_accounts

router = APIRouter(prefix="/transactions", tags=["transactions"])

@router.get("/", response_model=List[schemas.Transaction])
def get_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(models.Transaction)
    
    if start_date:
        query = query.filter(models.Transaction.date >= start_date)
    if end_date:
        query = query.filter(models.Transaction.date <= end_date)
    
    return query.order_by(models.Transaction.date.desc()).limit(limit).all()

@router.post("/", response_model=schemas.Transaction)
def create_transaction(transaction: schemas.TransactionCreate, db: Session = Depends(get_db)):
    """Create a transaction and process double-entry bookkeeping."""
    # Ensure default accounts exist
    ensure_default_accounts(db)
    
    # Create the transaction
    db_transaction = models.Transaction(**transaction.model_dump())
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    
    # Process double-entry bookkeeping
    process_transaction(db, db_transaction)
    
    return db_transaction

@router.delete("/{transaction_id}")
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """Delete a transaction and its journal entries."""
    # Delete journal entries first
    db.query(models.JournalEntry).filter(
        models.JournalEntry.transaction_id == transaction_id
    ).delete()
    
    # Delete transaction
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id
    ).first()
    
    if transaction:
        db.delete(transaction)
        db.commit()
        return {"message": "Transaction deleted"}
    
    return {"message": "Transaction not found"}
