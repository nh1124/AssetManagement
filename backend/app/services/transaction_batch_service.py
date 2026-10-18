from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models


def list_batches(
    db: Session, client_id: int, *, limit: int = 50, offset: int = 0,
) -> list[models.TransactionBatch]:
    return db.query(models.TransactionBatch).filter(
        models.TransactionBatch.client_id == client_id,
    ).order_by(models.TransactionBatch.created_at.desc(), models.TransactionBatch.id.desc()).offset(offset).limit(limit).all()


def get_batch(
    db: Session, client_id: int, batch_id: int,
) -> models.TransactionBatch | None:
    return db.query(models.TransactionBatch).filter(
        models.TransactionBatch.id == batch_id,
        models.TransactionBatch.client_id == client_id,
    ).first()


def create_batch(
    db: Session, client_id: int, data: dict, *, commit: bool = True,
) -> models.TransactionBatch:
    batch = models.TransactionBatch(**data, client_id=client_id)
    db.add(batch)
    if commit:
        db.commit()
        db.refresh(batch)
    else:
        db.flush()
    return batch
