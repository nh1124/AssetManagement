from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import transaction_batch_service
from ..workflows.transaction_batch_workflow import post_transaction_batch
from ..services.journal_legs import primary_accounts

router = APIRouter(prefix="/transaction-batches", tags=["transaction-batches"])


def _serialize_transaction(tx: models.Transaction) -> dict:
    from_account, to_account = primary_accounts(tx)
    return {
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
    }


def _serialize_batch(batch: models.TransactionBatch) -> dict:
    return {
        "id": batch.id,
        "label": batch.label,
        "source": batch.source,
        "input_payload": batch.input_payload or {},
        "created_at": batch.created_at,
        "transactions": [_serialize_transaction(tx) for tx in batch.transactions],
    }


@router.get("/", response_model=list[schemas.TransactionBatch])
def get_transaction_batches(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    batches = transaction_batch_service.list_batches(db, current_client.id, limit=limit, offset=offset)
    return [_serialize_batch(batch) for batch in batches]


@router.post("/", response_model=schemas.TransactionBatch)
def create_transaction_batch(
    payload: schemas.TransactionBatchCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return _serialize_batch(post_transaction_batch(db, current_client.id, payload))


@router.get("/{batch_id}", response_model=schemas.TransactionBatch)
def get_transaction_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    batch = transaction_batch_service.get_batch(db, current_client.id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Transaction batch not found")
    return _serialize_batch(batch)
