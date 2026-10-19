"""Automatic transaction edits own their commit and cache boundary."""
from sqlalchemy.orm import Session
from ..services import registry_service
from ..services.cache_service import invalidate_client


def save(db: Session, client_id: int, data: dict, entry_id: int | None = None):
    try:
        entry = registry_service.create_entry(db, client_id, data) if entry_id is None else registry_service.update_entry(db, client_id, entry_id, data)
        db.commit()
        invalidate_client(client_id)
        return entry
    except Exception:
        db.rollback()
        raise


def delete(db: Session, client_id: int, entry_id: int) -> bool:
    try:
        deleted = registry_service.delete_entry(db, client_id, entry_id)
        db.commit()
        invalidate_client(client_id)
        return deleted
    except Exception:
        db.rollback()
        raise
