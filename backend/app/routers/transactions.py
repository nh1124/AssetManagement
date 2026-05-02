from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.accounting_service import (
    ensure_default_accounts,
    process_transaction,
    revert_transaction,
    update_transaction as update_transaction_service,
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


@router.get("/")
def get_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    amount_min: Optional[float] = Query(None),
    amount_max: Optional[float] = Query(None),
    account_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    paginated: bool = Query(False),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    query = db.query(models.Transaction).filter(models.Transaction.client_id == current_client.id)

    if start_date:
        query = query.filter(models.Transaction.date >= start_date)
    if end_date:
        query = query.filter(models.Transaction.date <= end_date)
    if type:
        query = query.filter(models.Transaction.type == type)
    if category:
        query = query.filter(models.Transaction.category.ilike(f"%{category}%"))
    if amount_min is not None:
        query = query.filter(models.Transaction.amount >= amount_min)
    if amount_max is not None:
        query = query.filter(models.Transaction.amount <= amount_max)
    if account_id:
        query = query.filter(
            or_(
                models.Transaction.from_account_id == account_id,
                models.Transaction.to_account_id == account_id,
            )
        )
    if q:
        query = query.filter(models.Transaction.description.ilike(f"%{q}%"))

    total = query.count() if paginated else None
    txs = query.order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).offset(offset).limit(limit).all()
    items = [_serialize_transaction(tx) for tx in txs]
    if paginated:
        return {"items": items, "total": total}
    return items


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


@router.put("/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: int,
    payload: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Update a transaction and atomically rebuild its journal entries."""
    ensure_default_accounts(db, client_id=current_client.id)
    try:
        tx = update_transaction_service(db, transaction_id, payload, current_client.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _serialize_transaction(tx)


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
