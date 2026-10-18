from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import Invalid
from ..services import transaction_batch_service
from ..services.ledger_service import ensure_default_accounts
from .ledger_entry_workflow import record_entry


class BatchPostingError(Invalid):
    pass


def post_transaction_batch(
    db: Session, client_id: int, payload: schemas.TransactionBatchCreate,
) -> models.TransactionBatch:
    if not payload.transactions:
        raise BatchPostingError("At least one transaction is required")

    ensure_default_accounts(db, client_id=client_id)
    batch = transaction_batch_service.create_batch(
        db, client_id, payload.model_dump(exclude={"transactions"}), commit=False,
    )

    created: list[models.Transaction] = []
    try:
        for item in payload.transactions:
            # The batch owns association; an entry's supplied batch_id cannot override it.
            entry = item.model_copy(update={"batch_id": batch.id})
            created.append(record_entry(db, client_id, entry, commit=False))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise BatchPostingError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    for transaction in created:
        db.refresh(transaction)
    db.refresh(batch)
    return batch
