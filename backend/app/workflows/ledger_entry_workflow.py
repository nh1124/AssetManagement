from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.money import Money
from ..services import ledger_service
from ..services.fx_service import get_client_currency
from ..services.capsule_service import (
    CapsuleReservation,
    apply_capsule_rules_for_transaction,
    capsule_reservations_for_transaction,
    retract_capsule_reservations,
)
from .transaction_approval_workflow import approve_transaction_proposal


def record_entry(
    db: Session,
    client_id: int,
    payload: schemas.TransactionCreate,
    *,
    commit: bool = True,
) -> models.Transaction:
    data = payload.model_dump()
    if data["currency"] is None:
        data["currency"] = get_client_currency(db, client_id)
    data["amount_minor"] = Money.from_major(str(data.pop("amount")), data["currency"]).minor
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
    """Rebuild an entry's journal legs at its new amount, and its reservations.

    The rebuild itself belongs to the module that owns the legs, including the
    decision about what an amount-only change means for a compound entry, so
    this adds only the default accounts the payload may name.

    X3: the capsule rules are re-evaluated here. They used to run only at
    posting time, so an amended amount left the reservation it triggered at the
    old figure. Withdrawing the old reservations and evaluating the amended
    entry is one operation -- partway through, the entry and its reservations
    disagree -- so update_transaction is asked not to close the transaction and
    this function closes it once.
    """
    retract_capsule_reservations(db, client_id, transaction_id, commit=False)
    transaction = ledger_service.update_transaction(
        db, transaction_id, payload, client_id, commit=False,
    )
    if transaction is None:
        # Nothing was amended, so nothing should have been withdrawn either.
        db.rollback()
        return None
    try:
        apply_capsule_rules_for_transaction(db, transaction, commit=False)
        if commit:
            db.commit()
            db.refresh(transaction)
        return transaction
    except Exception:
        db.rollback()
        raise


def remove_entry(
    db: Session,
    client_id: int,
    transaction_id: int,
    *,
    commit: bool = True,
) -> bool:
    transaction = ledger_service.get_transaction(db, client_id, transaction_id)
    if not transaction:
        return False

    try:
        # X3: the reservations this entry caused go with it. A posted one takes
        # its transfer too, so money leaves the earmarked account -- the UI
        # confirms that before calling this.
        retract_capsule_reservations(db, client_id, transaction_id, commit=False)
        ledger_service.delete_transaction(db, transaction)
        if commit:
            db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def entry_capsule_reservations(
    db: Session, client_id: int, transaction_id: int,
) -> list[CapsuleReservation]:
    """What amending or deleting this entry would withdraw.

    The UI asks before it changes an entry, because a posted reservation takes
    its transfer with it when the entry that caused it is amended or deleted.
    """
    return capsule_reservations_for_transaction(db, client_id, transaction_id)


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
    return ledger_service.list_transactions(
        db, client_id, start_date=start_date, end_date=end_date,
        amount_min=amount_min, amount_max=amount_max, account_id=account_id,
        q=q, limit=limit, offset=offset, with_total=with_total,
    )


def get_entry(
    db: Session, client_id: int, transaction_id: int,
) -> models.Transaction | None:
    return ledger_service.get_transaction(db, client_id, transaction_id)


def approve_entry_proposal(
    db: Session, client_id: int, proposal_id: int,
) -> models.Transaction | None:
    proposal = ledger_service.get_proposal(db, client_id, proposal_id)
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
    proposal = ledger_service.get_proposal(db, client_id, proposal_id)
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
