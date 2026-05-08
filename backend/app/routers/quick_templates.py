from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.accounting_service import ensure_default_accounts, post_transaction_journal
from ..services.capsule_service import apply_capsule_rules_for_transaction

router = APIRouter(prefix="/quick-templates", tags=["quick-templates"])
batch_router = APIRouter(prefix="/transaction-batches", tags=["transaction-batches"])


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
        "batch_id": tx.batch_id,
        "from_account_name": tx.from_account_rel.name if tx.from_account_rel else None,
        "to_account_name": tx.to_account_rel.name if tx.to_account_rel else None,
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


def _validate_account_reference(
    db: Session,
    client_id: int,
    account_id: int | None,
    field_name: str,
) -> None:
    if account_id is None:
        return
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
        models.Account.is_active == True,
    ).first()
    if not account:
        raise HTTPException(status_code=400, detail=f"{field_name} account not found")


def _get_template(db: Session, client_id: int, template_id: int) -> models.QuickTemplate:
    template = db.query(models.QuickTemplate).filter(
        models.QuickTemplate.id == template_id,
        models.QuickTemplate.client_id == client_id,
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Quick template not found")
    return template


@router.get("/", response_model=list[schemas.QuickTemplate])
def get_quick_templates(
    tray: str | None = Query(None),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    query = db.query(models.QuickTemplate).filter(models.QuickTemplate.client_id == current_client.id)
    if tray:
        query = query.filter(models.QuickTemplate.tray == tray)
    if not include_inactive:
        query = query.filter(models.QuickTemplate.is_active == True)
    templates = query.order_by(
        models.QuickTemplate.tray,
        models.QuickTemplate.sort_order,
        models.QuickTemplate.name,
    ).all()
    return [_serialize_template(template) for template in templates]


@router.post("/", response_model=schemas.QuickTemplate)
def create_quick_template(
    payload: schemas.QuickTemplateCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    data = payload.model_dump()
    _validate_account_reference(db, current_client.id, data.get("default_from_account_id"), "default_from")
    _validate_account_reference(db, current_client.id, data.get("default_to_account_id"), "default_to")
    template = models.QuickTemplate(**data, client_id=current_client.id)
    db.add(template)
    db.commit()
    db.refresh(template)
    return _serialize_template(template)


@router.put("/{template_id}", response_model=schemas.QuickTemplate)
def update_quick_template(
    template_id: int,
    payload: schemas.QuickTemplateUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    template = _get_template(db, current_client.id, template_id)
    data = payload.model_dump(exclude_unset=True)
    if "default_from_account_id" in data:
        _validate_account_reference(db, current_client.id, data["default_from_account_id"], "default_from")
    if "default_to_account_id" in data:
        _validate_account_reference(db, current_client.id, data["default_to_account_id"], "default_to")
    for key, value in data.items():
        setattr(template, key, value)
    db.commit()
    db.refresh(template)
    return _serialize_template(template)


@router.delete("/{template_id}")
def delete_quick_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    template = _get_template(db, current_client.id, template_id)
    template.is_active = False
    db.commit()
    return {"message": "Quick template deactivated"}


@batch_router.get("/", response_model=list[schemas.TransactionBatch])
def get_transaction_batches(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    batches = db.query(models.TransactionBatch).filter(
        models.TransactionBatch.client_id == current_client.id,
    ).order_by(models.TransactionBatch.created_at.desc(), models.TransactionBatch.id.desc()).offset(offset).limit(limit).all()
    return [_serialize_batch(batch) for batch in batches]


@batch_router.post("/", response_model=schemas.TransactionBatch)
def create_transaction_batch(
    payload: schemas.TransactionBatchCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not payload.transactions:
        raise HTTPException(status_code=400, detail="At least one transaction is required")

    ensure_default_accounts(db, client_id=current_client.id)
    if payload.quick_template_id is not None:
        _get_template(db, current_client.id, payload.quick_template_id)

    batch = models.TransactionBatch(
        client_id=current_client.id,
        quick_template_id=payload.quick_template_id,
        label=payload.label,
        source=payload.source,
        input_payload=payload.input_payload,
    )
    db.add(batch)
    db.flush()

    created: list[models.Transaction] = []
    try:
        for item in payload.transactions:
            tx = models.Transaction(
                **item.model_dump(exclude={"batch_id"}),
                batch_id=batch.id,
                client_id=current_client.id,
            )
            db.add(tx)
            db.flush()
            post_transaction_journal(db, tx)
            created.append(tx)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for tx in created:
        db.refresh(tx)
        apply_capsule_rules_for_transaction(db, tx)
    db.refresh(batch)
    return _serialize_batch(batch)


@batch_router.get("/{batch_id}", response_model=schemas.TransactionBatch)
def get_transaction_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    batch = db.query(models.TransactionBatch).filter(
        models.TransactionBatch.id == batch_id,
        models.TransactionBatch.client_id == current_client.id,
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Transaction batch not found")
    return _serialize_batch(batch)
