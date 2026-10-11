from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models


def get(
    db: Session, client_id: int, change_request_id: int, *, for_update: bool = False,
) -> models.AiChangeRequest | None:
    query = db.query(models.AiChangeRequest).filter(
        models.AiChangeRequest.id == change_request_id,
        models.AiChangeRequest.client_id == client_id,
    )
    if for_update:
        # Serialize apply attempts so one approved request cannot write twice.
        query = query.with_for_update()
    return query.first()


def list_for_client(
    db: Session, client_id: int, *, status: str | None = None, limit: int = 100, offset: int = 0,
) -> list[models.AiChangeRequest]:
    query = db.query(models.AiChangeRequest).filter(models.AiChangeRequest.client_id == client_id)
    if status:
        query = query.filter(models.AiChangeRequest.status == status)
    return query.order_by(models.AiChangeRequest.created_at.desc(), models.AiChangeRequest.id.desc()).offset(offset).limit(limit).all()


def find_by_idempotency_key(
    db: Session, client_id: int, idempotency_key: str,
) -> models.AiChangeRequest | None:
    return db.query(models.AiChangeRequest).filter(
        models.AiChangeRequest.client_id == client_id,
        models.AiChangeRequest.idempotency_key == idempotency_key,
    ).first()


def create(
    db: Session, client_id: int, fields: dict, *, commit: bool = False,
) -> models.AiChangeRequest:
    row = models.AiChangeRequest(**fields, client_id=client_id)
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row
