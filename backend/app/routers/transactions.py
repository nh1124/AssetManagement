from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.accounting_service import process_transaction, ensure_default_accounts

router = APIRouter(prefix="/transactions", tags=["transactions"])

@router.get("/", response_model=List[schemas.Transaction])
def get_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    query = db.query(models.Transaction).filter(models.Transaction.client_id == current_client.id)
    
    if start_date:
        query = query.filter(models.Transaction.date >= start_date)
    if end_date:
        query = query.filter(models.Transaction.date <= end_date)
    
    return query.order_by(models.Transaction.date.desc()).limit(limit).all()

@router.post("/", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create a transaction for a specific client and process double-entry bookkeeping."""
    # Ensure default accounts exist for this client
    ensure_default_accounts(db, client_id=current_client.id)
    
    # Create the transaction
    db_transaction = models.Transaction(**transaction.model_dump(), client_id=current_client.id)
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    
    # Process double-entry bookkeeping (this should be client-aware via account lookup)
    process_transaction(db, db_transaction)
    
    return db_transaction

@router.delete("/{transaction_id}")
def delete_transaction(
    transaction_id: int, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Delete a transaction and its journal entries for a specific client."""
    # Find transaction first to ensure it belongs to the client
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.client_id == current_client.id
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Delete journal entries first
    db.query(models.JournalEntry).filter(
        models.JournalEntry.transaction_id == transaction_id
    ).delete()
    
    # Delete transaction
    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted"}

