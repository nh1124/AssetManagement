"""Write-downs recorded or corrected by hand from the ledger (R2).

The depreciation service owns the record and its entry; this closes the unit of
work and refuses a client the record does not belong to.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.money import Money
from ..services import depreciation_service
from ..services.cache_service import invalidate_client
from ..services.fx_service import get_client_currency


def _minor(db: Session, client_id: int, amount: float | None) -> int | None:
    return None if amount is None else Money.from_major(str(amount), get_client_currency(db, client_id)).minor


def record(db: Session, client_id: int, payload: schemas.DepreciationRecord) -> models.ProductDepreciation:
    try:
        _, row = depreciation_service.record(
            db, client_id, payload.product_id, period=payload.period, amount_minor=_minor(db, client_id, payload.amount),
            posting_date=payload.date, expense_account_id=payload.expense_account_id, asset_account_id=payload.asset_account_id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return row


def amend(db: Session, client_id: int, depreciation_id: int, payload: schemas.DepreciationAmend) -> models.ProductDepreciation:
    try:
        _, row = depreciation_service.amend(
            db, client_id, depreciation_id, amount_minor=_minor(db, client_id, payload.amount),
            posting_date=payload.date, expense_account_id=payload.expense_account_id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return row


def preview(db: Session, client_id: int, product_id: int) -> dict:
    return depreciation_service.preview(db, client_id, product_id)
