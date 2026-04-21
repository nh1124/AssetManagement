from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.accounting_service import (
    ensure_default_accounts,
    process_transaction,
    revert_transaction,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _serialize_transaction(tx: models.Transaction) -> dict:
    return {
        "id": tx.id,
        "date": tx.date,
        "description": tx.description,
        "amount": tx.amount,
        "type": tx.type,
        "category": tx.category,
        "currency": tx.currency,
        "from_account_id": tx.from_account_id,
        "to_account_id": tx.to_account_id,
        "from_account_name": tx.from_account_rel.name if tx.from_account_rel else None,
        "to_account_name": tx.to_account_rel.name if tx.to_account_rel else None,
    }


@router.get("/", response_model=List[schemas.Transaction])
def get_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    query = db.query(models.Transaction).filter(models.Transaction.client_id == current_client.id)

    if start_date:
        query = query.filter(models.Transaction.date >= start_date)
    if end_date:
        query = query.filter(models.Transaction.date <= end_date)

    txs = query.order_by(models.Transaction.date.desc()).limit(limit).all()
    return [_serialize_transaction(tx) for tx in txs]


@router.post("/", response_model=schemas.Transaction)
def create_transaction(
    transaction: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Create a transaction for a specific client and process double-entry bookkeeping."""
    ensure_default_accounts(db, client_id=current_client.id)

    db_transaction = models.Transaction(**transaction.model_dump(), client_id=current_client.id)
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)

    process_transaction(db, db_transaction)
    db.refresh(db_transaction)

    return _serialize_transaction(db_transaction)


@router.delete("/{transaction_id}")
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Delete a transaction and its journal entries for a specific client."""
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.client_id == current_client.id,
    ).first()

    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    revert_transaction(db, transaction)

    db.query(models.JournalEntry).filter(
        models.JournalEntry.transaction_id == transaction_id
    ).delete()

    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted"}
