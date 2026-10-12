from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid
from .fx_service import get_client_currency


def _validate_account_reference(
    db: Session,
    client_id: int,
    account_id: int | None,
    field_name: str,
) -> None:
    if account_id is None:
        return
    # Account-id foreign keys alone cannot enforce client ownership or activity.
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
        models.Account.is_active == True,
    ).first()
    if not account:
        raise Invalid(f"{field_name} account not found")


def _get_template(
    db: Session, client_id: int, template_id: int,
) -> models.QuickTemplate | None:
    return db.query(models.QuickTemplate).filter(
        models.QuickTemplate.id == template_id,
        models.QuickTemplate.client_id == client_id,
    ).first()


def list_templates(
    db: Session, client_id: int, *, tray: str | None = None, include_inactive: bool = False,
) -> list[models.QuickTemplate]:
    query = db.query(models.QuickTemplate).filter(models.QuickTemplate.client_id == client_id)
    if tray:
        query = query.filter(models.QuickTemplate.tray == tray)
    if not include_inactive:
        query = query.filter(models.QuickTemplate.is_active == True)
    return query.order_by(
        models.QuickTemplate.tray,
        models.QuickTemplate.sort_order,
        models.QuickTemplate.name,
    ).all()


def create_template(
    db: Session, client_id: int, data: dict, *, commit: bool = True,
) -> models.QuickTemplate:
    if data.get("default_currency") is None:
        data = {**data, "default_currency": get_client_currency(db, client_id)}
    _validate_account_reference(db, client_id, data.get("default_from_account_id"), "default_from")
    _validate_account_reference(db, client_id, data.get("default_to_account_id"), "default_to")
    template = models.QuickTemplate(**data, client_id=client_id)
    db.add(template)
    if commit:
        db.commit()
        db.refresh(template)
    else:
        db.flush()
    return template


def update_template(
    db: Session, client_id: int, template_id: int, data: dict, *, commit: bool = True,
) -> models.QuickTemplate | None:
    template = _get_template(db, client_id, template_id)
    if template is None:
        return None
    if "default_currency" in data and data["default_currency"] is None:
        data = {**data, "default_currency": template.default_currency}
    if "default_from_account_id" in data:
        _validate_account_reference(db, client_id, data["default_from_account_id"], "default_from")
    if "default_to_account_id" in data:
        _validate_account_reference(db, client_id, data["default_to_account_id"], "default_to")
    for key, value in data.items():
        setattr(template, key, value)
    if commit:
        db.commit()
        db.refresh(template)
    else:
        db.flush()
    return template


def delete_template(
    db: Session, client_id: int, template_id: int, *, commit: bool = True,
) -> bool | None:
    template = _get_template(db, client_id, template_id)
    if template is None:
        return None
    template.is_active = False
    if commit:
        db.commit()
    else:
        db.flush()
    return True


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
) -> models.TransactionBatch | None:
    template_id = data.get("quick_template_id")
    if template_id is not None and _get_template(db, client_id, template_id) is None:
        return None
    batch = models.TransactionBatch(**data, client_id=client_id)
    db.add(batch)
    if commit:
        db.commit()
        db.refresh(batch)
    else:
        db.flush()
    return batch
