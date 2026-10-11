from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import quick_template_service
from ..workflows.transaction_batch_workflow import BatchPostingError, post_transaction_batch
from ..services.journal_legs import primary_accounts

router = APIRouter(prefix="/quick-templates", tags=["quick-templates"])
batch_router = APIRouter(prefix="/transaction-batches", tags=["transaction-batches"])


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


def _serialize_template(template: models.QuickTemplate) -> dict:
    return {
        "id": template.id,
        "tray": template.tray,
        "name": template.name,
        "template_kind": template.template_kind,
        "description": template.description,
        "category": template.category,
        "default_currency": template.default_currency,
        "default_from_account_id": template.default_from_account_id,
        "default_to_account_id": template.default_to_account_id,
        "default_from_account_name": template.default_from_account.name if template.default_from_account else None,
        "default_to_account_name": template.default_to_account.name if template.default_to_account else None,
        "config": template.config or {},
        "sort_order": template.sort_order,
        "is_active": template.is_active,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }


def _serialize_batch(batch: models.TransactionBatch) -> dict:
    return {
        "id": batch.id,
        "quick_template_id": batch.quick_template_id,
        "label": batch.label,
        "source": batch.source,
        "input_payload": batch.input_payload or {},
        "created_at": batch.created_at,
        "transactions": [_serialize_transaction(tx) for tx in batch.transactions],
    }


@router.get("/", response_model=list[schemas.QuickTemplate])
def get_quick_templates(
    tray: str | None = Query(None),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    templates = quick_template_service.list_templates(
        db, current_client.id, tray=tray, include_inactive=include_inactive,
    )
    return [_serialize_template(template) for template in templates]


@router.post("/", response_model=schemas.QuickTemplate)
def create_quick_template(
    payload: schemas.QuickTemplateCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    template = quick_template_service.create_template(db, current_client.id, payload.model_dump())
    return _serialize_template(template)


@router.put("/{template_id}", response_model=schemas.QuickTemplate)
def update_quick_template(
    template_id: int,
    payload: schemas.QuickTemplateUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    template = quick_template_service.update_template(
        db, current_client.id, template_id, payload.model_dump(exclude_unset=True),
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Quick template not found")
    return _serialize_template(template)


@router.delete("/{template_id}")
def delete_quick_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if quick_template_service.delete_template(db, current_client.id, template_id) is None:
        raise HTTPException(status_code=404, detail="Quick template not found")
    return {"message": "Quick template deactivated"}


@batch_router.get("/", response_model=list[schemas.TransactionBatch])
def get_transaction_batches(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    batches = quick_template_service.list_batches(db, current_client.id, limit=limit, offset=offset)
    return [_serialize_batch(batch) for batch in batches]


@batch_router.post("/", response_model=schemas.TransactionBatch)
def create_transaction_batch(
    payload: schemas.TransactionBatchCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        batch = post_transaction_batch(db, current_client.id, payload)
    except BatchPostingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if batch is None:
        raise HTTPException(status_code=404, detail="Quick template not found")
    return _serialize_batch(batch)


@batch_router.get("/{batch_id}", response_model=schemas.TransactionBatch)
def get_transaction_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    batch = quick_template_service.get_batch(db, current_client.id, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Transaction batch not found")
    return _serialize_batch(batch)
