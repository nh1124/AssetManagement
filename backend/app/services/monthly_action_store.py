from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .money_storage import minor_fields, money_client_currency

from .. import models


def get(
    db: Session, client_id: int, action_id: int, *, for_update: bool = False,
) -> models.MonthlyAction | None:
    query = db.query(models.MonthlyAction).filter(
        models.MonthlyAction.id == action_id,
        models.MonthlyAction.client_id == client_id,
    )
    if for_update:
        # Serialize edits/deletes with apply/skip and refresh any previously loaded state.
        query = query.with_for_update().populate_existing()
    return query.first()


def list_for_client(
    db: Session, client_id: int, *, period: str | None = None,
    status: str | None = None, target_period: str | None = None,
) -> list[models.MonthlyAction]:
    query = db.query(models.MonthlyAction).filter(models.MonthlyAction.client_id == client_id)
    if period:
        query = query.filter(models.MonthlyAction.source_period == period)
    if target_period:
        query = query.filter(models.MonthlyAction.target_period == target_period)
    if status:
        query = query.filter(models.MonthlyAction.status == status)
    return query.order_by(models.MonthlyAction.created_at.desc(), models.MonthlyAction.id.desc()).all()


def list_due(db: Session, client_id: int, today: date) -> list[models.MonthlyAction]:
    return db.query(models.MonthlyAction).filter(
        models.MonthlyAction.client_id == client_id,
        models.MonthlyAction.status.in_(["pending", "failed"]),
        models.MonthlyAction.target_period <= today.strftime("%Y-%m"),
    ).order_by(models.MonthlyAction.target_period, models.MonthlyAction.id).all()


def create(
    db: Session, client_id: int, fields: dict, *, commit: bool = False,
) -> models.MonthlyAction:
    row = models.MonthlyAction(**minor_fields(fields, money_client_currency(db, client_id), 'amount'), client_id=client_id)
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def update(db: Session, client_id: int, row: models.MonthlyAction, fields: dict) -> None:
    values = minor_fields(fields, money_client_currency(db, client_id), 'amount')
    for name, value in values.items():
        setattr(row, name, value)
    db.flush()


def delete(db: Session, row: models.MonthlyAction) -> None:
    db.delete(row)
