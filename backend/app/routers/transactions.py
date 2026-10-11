from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.ai_policy_service import assert_direct_ledger_write_allowed
from ..services.ledger_service import list_proposals as list_proposals_service
from ..services.cache_service import invalidate_client
from ..services.journal_legs import primary_accounts
from ..workflows.ledger_entry_workflow import (
    record_entry,
    amend_entry,
    remove_entry,
    list_entries,
    approve_entry_proposal,
    reject_entry_proposal,
)

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
    txs, total = list_entries(
        db,
        current_client.id,
        start_date=start_date,
        end_date=end_date,
        amount_min=amount_min,
        amount_max=amount_max,
        account_id=account_id,
        q=q,
        limit=limit,
        offset=offset,
        with_total=paginated,
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
    # Defaulted because several tests call these endpoints as plain
    # functions; FastAPI always injects the real request over HTTP.
    request: Request = None,
):
    """Create a transaction for a specific client and process double-entry bookkeeping."""
    assert_direct_ledger_write_allowed(
        db,
        current_client.id,
        mcp_client_id=request.headers.get("x-mcp-client-id") if request else None,
        risk="medium",
    )
    db_transaction = record_entry(db, current_client.id, transaction)
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
    try:
        transaction = approve_entry_proposal(db, current_client.id, proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction proposal not found")
    invalidate_client(current_client.id)
    return _serialize_transaction(transaction)


@router.post("/proposals/{proposal_id}/reject", response_model=schemas.TransactionProposal)
def reject_proposal(
    proposal_id: int,
    decision: schemas.TransactionProposalDecision,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        proposal = reject_entry_proposal(
            db, current_client.id, proposal_id, note=decision.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if proposal is None:
        raise HTTPException(status_code=404, detail="Transaction proposal not found")
    invalidate_client(current_client.id)
    return proposal


@router.put("/{transaction_id}", response_model=schemas.Transaction)
def update_transaction(
    transaction_id: int,
    payload: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
    # Defaulted because several tests call these endpoints as plain
    # functions; FastAPI always injects the real request over HTTP.
    request: Request = None,
):
    """Update a transaction and atomically rebuild its journal entries."""
    assert_direct_ledger_write_allowed(
        db,
        current_client.id,
        mcp_client_id=request.headers.get("x-mcp-client-id") if request else None,
        risk="medium",
    )
    try:
        tx = amend_entry(db, current_client.id, transaction_id, payload)
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
    # Defaulted because several tests call these endpoints as plain
    # functions; FastAPI always injects the real request over HTTP.
    request: Request = None,
):
    """Delete a transaction and its journal entries for a specific client."""
    assert_direct_ledger_write_allowed(
        db,
        current_client.id,
        mcp_client_id=request.headers.get("x-mcp-client-id") if request else None,
        risk="medium",
    )
    if not remove_entry(db, current_client.id, transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    invalidate_client(current_client.id)
    return {"message": "Transaction deleted"}
