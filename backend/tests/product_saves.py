"""Product saves that confirm their earmark changes, for tests about something else."""
from app.domain.errors import Conflict


def confirmed(save, db, *args, **kwargs):
    # The refused attempt is the preview; the app discards its session, a test rolls it back.
    try:
        return save(db, *args, **kwargs)
    except Conflict as refusal:
        if not isinstance(refusal.payload, dict) or refusal.payload.get("code") != "reserve_changes_unconfirmed":
            raise
        db.rollback()
        return save(db, *args, reserve_fingerprint=refusal.payload["fingerprint"], **kwargs)
