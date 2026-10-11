from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..services import ledger_service
from ..services.capsule_service import apply_capsule_rules_for_transaction
from .transaction_approval_workflow import approve_transaction_proposal


def record_entry(
    db: Session,
    client_id: int,
    payload: schemas.TransactionCreate,
    *,
    commit: bool = True,
) -> models.Transaction:
    ledger_service.ensure_default_accounts(db, client_id=client_id, commit=commit)

    data = payload.model_dump()
    legs = data.pop("legs", None)
    from_account_id = data.pop("from_account_id", None)
    to_account_id = data.pop("to_account_id", None)
    try:
        transaction = ledger_service.create_transaction(
            db,
            client_id=client_id,
            legs=legs,
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            **data,
        )
        apply_capsule_rules_for_transaction(db, transaction, commit=False)
        if commit:
            db.commit()
            db.refresh(transaction)
        return transaction
    except Exception:
        db.rollback()
        raise


def amend_entry(
    db: Session,
    client_id: int,
    transaction_id: int,
    payload: schemas.TransactionUpdate,
    *,
    commit: bool = True,
) -> models.Transaction | None:
    """Rebuild an entry's journal legs at its new amount.

    The rebuild itself belongs to the module that owns the legs, including the
    decision about what an amount-only change means for a compound entry, so
    this adds only the default accounts the payload may name.

    Note what it does not do: the capsule rules are not re-evaluated here, so an
    amended amount leaves any reservation it triggered at the old figure. That
    predates this wave and is recorded as X3 in docs/specs/layering.md.
    """
    ledger_service.ensure_default_accounts(db, client_id=client_id, commit=commit)
    return ledger_service.update_transaction(
        db, transaction_id, payload, client_id, commit=commit,
    )


def remove_entry(
    db: Session,
    client_id: int,
    transaction_id: int,
    *,
    commit: bool = True,
) -> bool:
    transaction = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.client_id == client_id,
    ).first()
    if not transaction:
        return False

    try:
        ledger_service.delete_transaction(db, transaction)
        if commit:
            db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def list_entries(
    db: Session,
    client_id: int,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    account_id: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    with_total: bool = False,
) -> tuple[list[models.Transaction], int | None]:
    query = db.query(models.Transaction).filter(models.Transaction.client_id == client_id)

    if start_date:
        query = query.filter(models.Transaction.date >= start_date)
    if end_date:
        query = query.filter(models.Transaction.date <= end_date)
    if amount_min is not None:
        query = query.filter(models.Transaction.amount >= amount_min)
    if amount_max is not None:
        query = query.filter(models.Transaction.amount <= amount_max)
    if account_id:
        # A leg query, not from/to: a compound entry touches accounts that the
        # denormalised columns cannot name.
        query = query.filter(
            models.Transaction.journal_entries.any(models.JournalEntry.account_id == account_id)
        )
    if q:
        query = query.filter(models.Transaction.description.ilike(f"%{q}%"))

    total = query.count() if with_total else None
    transactions = (
        query.options(
            selectinload(models.Transaction.journal_entries).selectinload(models.JournalEntry.account)
        )
        .order_by(models.Transaction.date.desc(), models.Transaction.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return transactions, total


def _get_proposal(db: Session, client_id: int, proposal_id: int) -> models.TransactionProposal | None:
    return db.query(models.TransactionProposal).filter(
        models.TransactionProposal.id == proposal_id,
        models.TransactionProposal.client_id == client_id,
    ).first()


def approve_entry_proposal(
    db: Session, client_id: int, proposal_id: int,
) -> models.Transaction | None:
    proposal = _get_proposal(db, client_id, proposal_id)
    if proposal is None:
        return None
    try:
        transaction = approve_transaction_proposal(db, proposal, actor_client_id=client_id)
        db.commit()
        db.refresh(transaction)
        return transaction
    except Exception:
        db.rollback()
        raise


def reject_entry_proposal(
    db: Session, client_id: int, proposal_id: int, *, note: str | None = None,
) -> models.TransactionProposal | None:
    proposal = _get_proposal(db, client_id, proposal_id)
    if proposal is None:
        return None
    try:
        ledger_service.reject_proposal(db, proposal, actor_client_id=client_id, note=note)
        db.commit()
        db.refresh(proposal)
        return proposal
    except Exception:
        db.rollback()
        raise
