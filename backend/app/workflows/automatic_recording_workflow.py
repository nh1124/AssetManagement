"""Daily and sign-in posting boundary for automatic transactions and depreciation."""
from __future__ import annotations

import logging
from datetime import date
from sqlalchemy.orm import Session

from ..domain.errors import Invalid
from ..services import automatic_recording_service, depreciation_service, product_service, registry_service
from ..services.cache_service import invalidate_client

logger = logging.getLogger(__name__)


def process_due(db: Session, client_id: int, *, today: date | None = None) -> dict:
    effective_today = today or registry_service.client_today(db, client_id)
    try:
        processed = automatic_recording_service.post_due(db, client_id, effective_today)
        db.commit()
    except Exception:
        db.rollback()
        raise
    depreciation = []
    for product in product_service.list_products(db, client_id, is_asset=True):
        if not product.auto_depreciation:
            continue
        try:
            rows = depreciation_service.post_due(db, client_id, product.id, today=effective_today)
            depreciation.append({"product_id": product.id, "periods": [row.period for row in rows]})
            db.commit()
        except Invalid as error:
            db.rollback()
            depreciation.append({"product_id": product.id, "periods": [], "skipped": str(error)})
    if processed or any(row["periods"] for row in depreciation):
        invalidate_client(client_id)
    return {"automatic_transactions": processed, "depreciation": depreciation}


def process_due_all(db: Session, *, today: date | None = None) -> None:
    for client_id in registry_service.automatic_client_ids(db):
        try:
            process_due(db, client_id, today=today)
        except Exception:
            db.rollback()
            logger.exception("Automatic recording failed for client_id=%s", client_id)
