from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.ledger_service import (
    ensure_default_accounts,
    reject_proposal as reject_proposal_service,
    list_proposals as list_proposals_service,
    create_transaction as create_transaction_service,
    delete_transaction as delete_transaction_service,
    update_transaction as update_transaction_service,
)
from ..services.cache_service import invalidate_client
from ..services.capsule_service import apply_capsule_rules_for_transaction
from ..services.journal_legs import primary_accounts
from ..workflows.transaction_approval_workflow import approve_transaction_proposal

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _serialize_leg(entry: models.JournalEntry) -> dict:
    account = entry.account
    return {
        "id": entry.id,
        "account_id": entry.account_id,
        "account_name": account.name if account else None,
        "account_type": account.account_type if account else None,
        "debit": entry.debit or 0.0,
        "credit": entry.credit or 0.0,
        "memo": entry.memo,
    }


def _serialize_transaction(tx: models.Transaction, *, account_id: int | None = None) -> dict:
    legs = sorted(
        tx.journal_entries,
        key=lambda entry: (entry.sort_order if entry.sort_order is not None else 0, entry.id or 0),
    )
    from_account, to_account = primary_accounts(tx)
    row = {
        "id": tx.id,
        "date": tx.date,
        "description": tx.description,
        "amount": tx.amount,
        "currency": tx.currency,
        "from_account_id": from_account.id if from_account else None,
        "to_account_id": to_account.id if to_account else None,
        "batch_id": tx.batch_id,
        "from_account_name": from_account.name if from_account else None,
        "to_account_name": to_account.name if to_account else None,
        "legs": [_serialize_leg(entry) for entry in legs],
    }
    if account_id:
        # Filtered by account, the useful figure is what moved on that account.
        # A compound entry's total says nothing about any one of its legs.
        row["matched_debit"] = sum(
            (entry.debit or 0.0) for entry in legs if entry.account_id == account_id
        )
        row["matched_credit"] = sum(
            (entry.credit or 0.0) for entry in legs if entry.account_id == account_id
        )
    return row


@router.get("/")
def get_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
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
    if amount_min is not None:
        query = query.filter(models.Transaction.amount >= amount_min)
    if amount_max is not None:
        query = query.filter(models.Transaction.amount <= amount_max)
    if account_id:
        # A leg query, not from/to: a compound entry touches accounts that the
        # denormalised columns cannot name.
        query = query.filter(
            models.Transaction.journal_entries.any(models.JournalEntry.account_id == account_id)
        )
    if q:
        query = query.filter(models.Transaction.description.ilike(f"%{q}%"))

    total = query.count() if paginated else None
    txs = (
        query.options(
            selectinload(models.Transaction.journal_entries).selectinload(models.JournalEntry.account)
        )
        .order_by(models.Transaction.date.desc(), models.Transaction.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [_serialize_transaction(tx, account_id=account_id) for tx in txs]
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

    data = transaction.model_dump()
    legs = data.pop("legs", None)
    from_account_id = data.pop("from_account_id", None)
    to_account_id = data.pop("to_account_id", None)
    try:
        db_transaction = create_transaction_service(
            db,
            client_id=current_client.id,
            legs=legs,
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            **data,
        )
        apply_capsule_rules_for_transaction(db, db_transaction, commit=False)
        db.commit()
        db.refresh(db_transaction)
    except Exception:
        db.rollback()
        raise
    invalidate_client(current_client.id)

    return _serialize_transaction(db_transaction)


@router.get("/proposals", response_model=list[schemas.TransactionProposal])
def get_proposals(
    status: Optional[str] = Query(None),
    origin: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return list_proposals_service(db, current_client.id, status=status, origin=origin)


@router.post("/proposals/{proposal_id}/approve", response_model=schemas.Transaction)
def approve_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    proposal = db.query(models.TransactionProposal).filter(
        models.TransactionProposal.id == proposal_id,
        models.TransactionProposal.client_id == current_client.id,
    ).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Transaction proposal not found")
    try:
        transaction = approve_transaction_proposal(db, proposal, actor_client_id=current_client.id)
        db.commit()
        db.refresh(transaction)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    invalidate_client(current_client.id)
    return _serialize_transaction(transaction)


@router.post("/proposals/{proposal_id}/reject", response_model=schemas.TransactionProposal)
def reject_proposal(
    proposal_id: int,
    decision: schemas.TransactionProposalDecision,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    proposal = db.query(models.TransactionProposal).filter(
        models.TransactionProposal.id == proposal_id,
        models.TransactionProposal.client_id == current_client.id,
    ).first()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Transaction proposal not found")
    try:
        reject_proposal_service(
            db,
            proposal,
            actor_client_id=current_client.id,
            note=decision.note,
        )
        db.commit()
        db.refresh(proposal)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    invalidate_client(current_client.id)
    return proposal


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
    invalidate_client(current_client.id)
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

    try:
        delete_transaction_service(db, transaction)
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(current_client.id)
    return {"message": "Transaction deleted"}
