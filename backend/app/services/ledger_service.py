"""Ledger Service - double-entry bookkeeping primitives.

Layer 1. Owns transaction posting, journal entries and account balance
mutation. Depends on ORM models and pure journal rules: never on planning,
registry or reporting.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..domain.errors import Invalid, NotFound
from ..domain.money import Money
from ..domain.journal import (
    BALANCE_TOLERANCE,
    DEBIT_NORMAL_TYPES,
    Leg,
    coerce_leg,
    signed_delta,
    simple_legs,
    validate_legs,
)


def list_accounts(
    db: Session, client_id: int, *, account_type: str | None = None,
    is_active: bool = True, ordered: bool = True,
) -> list[models.Account]:
    query = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.is_active == is_active,
    )
    if account_type:
        query = query.filter(models.Account.account_type == account_type)
    if ordered:
        query = query.order_by(models.Account.account_type, models.Account.name)
    return query.all()


def list_asset_accounts(db: Session, client_id: int) -> list[models.Account]:
    # Allocation has always considered inactive assets as well as active ones.
    return db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "asset",
    ).all()


def find_account_ids(db: Session, client_id: int, account_ids: Sequence[int]) -> set[int]:
    found = db.query(models.Account.id).filter(
        models.Account.client_id == client_id,
        models.Account.id.in_(account_ids),
    ).all()
    return {row[0] for row in found}


def get_expense_account(db: Session, client_id: int, account_id: int) -> models.Account | None:
    # Product budgeting requires an expense account belonging to its client.
    return db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
        models.Account.account_type == "expense",
    ).first()


def get_account(db: Session, client_id: int, account_id: int) -> models.Account | None:
    # Product categories and capsule contributions need the client's account;
    # each workflow decides what that account means for its request.
    return _get_account_by_id(db, account_id, client_id)


def _validate_parent(
    db: Session,
    client_id: int,
    account_type: str,
    parent_id: int | None,
    account_id: int | None = None,
) -> None:
    if parent_id is None:
        return
    if account_id is not None and parent_id == account_id:
        raise Invalid("Account cannot be its own parent")

    parent = db.query(models.Account).filter(
        models.Account.id == parent_id,
        models.Account.client_id == client_id,
        models.Account.is_active == True,
    ).first()
    if not parent:
        raise NotFound("Parent account not found")
    if parent.account_type != account_type:
        raise Invalid("Parent account must have the same account_type")

    seen = set()
    current = parent
    while current:
        if current.id in seen:
            raise Invalid("Account hierarchy cycle detected")
        if account_id is not None and current.id == account_id:
            raise Invalid("Account hierarchy cycle detected")
        seen.add(current.id)
        if current.parent_id is None:
            break
        current = db.query(models.Account).filter(
            models.Account.id == current.parent_id,
            models.Account.client_id == client_id,
        ).first()


def _normalize_liability_settings(payload: dict, account_type: str) -> None:
    liability_keys = {
        "liability_closing_day",
        "liability_payment_day",
        "liability_payment_month_offset",
        "liability_payment_policy",
        "liability_minimum_payment",
        "liability_fixed_payment_amount",
        "liability_installment_months",
        "liability_revolving_rate",
    }
    if account_type != "liability":
        for key in liability_keys:
            payload.pop(key, None)
        return
    if payload.get("liability_payment_policy") is None:
        payload["liability_payment_policy"] = "full"
    if payload.get("liability_payment_month_offset") is None:
        payload["liability_payment_month_offset"] = 0
    for key in ("liability_closing_day", "liability_payment_day"):
        value = payload.get(key)
        if value is not None and not 1 <= value <= 31:
            raise Invalid(f"{key} must be between 1 and 31")
    offset = payload.get("liability_payment_month_offset")
    if offset is not None and not 0 <= offset <= 24:
        raise Invalid("liability_payment_month_offset must be between 0 and 24")
    installment_months = payload.get("liability_installment_months")
    if installment_months is not None and installment_months < 1:
        raise Invalid("liability_installment_months must be positive")
    for key in ("liability_minimum_payment", "liability_fixed_payment_amount", "liability_revolving_rate"):
        value = payload.get(key)
        if value is not None and value < 0:
            raise Invalid(f"{key} must not be negative")


def create_account(
    db: Session, client_id: int, data: dict, *, commit: bool = True,
) -> models.Account:
    payload = data.copy()
    if abs(payload.pop("balance", 0) or 0) > 0.01:
        raise Invalid(
            "Journal is the source of truth. Create an opening-balance transaction instead of setting account.balance.",
        )
    _normalize_liability_settings(payload, payload["account_type"])
    _validate_parent(db, client_id, payload["account_type"], payload.get("parent_id"))
    account = models.Account(**payload, client_id=client_id)
    db.add(account)
    if commit:
        db.commit()
        db.refresh(account)
    else:
        db.flush()
    return account


def update_account(
    db: Session, client_id: int, account_id: int, data: dict, *, commit: bool = True,
) -> models.Account | None:
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
    ).first()
    if not account:
        return None
    update_data = data.copy()
    if "balance" in update_data:
        raise Invalid(
            "Journal is the source of truth. Use transactions to change balances.",
        )
    if "parent_id" in update_data:
        _validate_parent(
            db, client_id, account.account_type, update_data["parent_id"], account_id=account.id,
        )
    _normalize_liability_settings(update_data, account.account_type)
    for key, value in update_data.items():
        setattr(account, key, value)
    if commit:
        db.commit()
        db.refresh(account)
    else:
        db.flush()
    return account


def delete_account(
    db: Session, client_id: int, account_id: int, *, commit: bool = True,
) -> bool:
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
    ).first()
    if not account:
        return False
    child_count = db.query(models.Account).filter(
        models.Account.parent_id == account_id,
        models.Account.client_id == client_id,
        models.Account.is_active == True,
    ).count()
    if child_count:
        raise Invalid("Account has child accounts")

    # The FK check protects active templates without mutating their feature.
    template_count = db.query(models.QuickTemplate).filter(
        models.QuickTemplate.client_id == client_id,
        models.QuickTemplate.is_active == True,
        (
            (models.QuickTemplate.default_from_account_id == account_id)
            | (models.QuickTemplate.default_to_account_id == account_id)
        ),
    ).count()
    if template_count:
        raise Invalid(
            "Account is used by active quick templates. Delete or update those templates first.",
        )
    account.is_active = False
    if commit:
        db.commit()
    else:
        db.flush()
    return True


# Default accounts to create on startup
DEFAULT_ACCOUNTS = [
    # Asset accounts
    {"name": "cash", "account_type": "asset"},
    {"name": "bank", "account_type": "asset"},
    {"name": "investment", "account_type": "asset"},
    {"name": "savings", "account_type": "asset"},
    # Liability accounts
    {"name": "credit", "account_type": "liability"},
    {"name": "loan", "account_type": "liability"},
    # Income accounts
    {"name": "salary", "account_type": "income"},
    {"name": "bonus", "account_type": "income"},
    {"name": "investment_income", "account_type": "income"},
    # Expense accounts
    {"name": "food", "account_type": "expense"},
    {"name": "transport", "account_type": "expense"},
    {"name": "entertainment", "account_type": "expense"},
    {"name": "utilities", "account_type": "expense"},
    {"name": "shopping", "account_type": "expense"},
    {"name": "expense", "account_type": "expense"},  # Generic expense
]


def ensure_default_accounts(db: Session, client_id: int, *, commit: bool = True) -> None:
    """Create default accounts for a client if they don't exist."""
    for acc in DEFAULT_ACCOUNTS:
        existing = db.query(models.Account).filter(
            models.Account.name == acc["name"],
            models.Account.client_id == client_id,
        ).first()
        if not existing:
            db.add(models.Account(**acc, client_id=client_id))
    if commit:
        db.commit()
    else:
        db.flush()


def get_or_create_account(
    db: Session,
    name: str,
    client_id: int,
    account_type: str = "expense",
    *,
    commit: bool = True,
) -> models.Account:
    """Get account by name or create it for a specific client."""
    normalized = (name or "").strip().lower()
    if not normalized:
        normalized = "expense"

    account = db.query(models.Account).filter(
        models.Account.name == normalized,
        models.Account.client_id == client_id,
    ).first()
    if not account:
        account = models.Account(
            name=normalized,
            account_type=account_type,
            client_id=client_id,
        )
        db.add(account)
        if commit:
            db.commit()
            db.refresh(account)
        else:
            db.flush()
    return account


def _get_account_by_id(
    db: Session,
    account_id: Optional[int],
    client_id: int,
) -> Optional[models.Account]:
    if not account_id:
        return None
    return db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
    ).first()


def calculate_account_journal_balance(
    db: Session,
    account: models.Account,
    as_of_date: date | None = None,
) -> float:
    """
    Calculate an account balance from journal entries only.
    Account.balance is treated as a denormalized cache, not source-of-truth.
    """
    query = db.query(
        func.sum(models.JournalEntry.debit).label("total_debit"),
        func.sum(models.JournalEntry.credit).label("total_credit"),
    ).filter(models.JournalEntry.account_id == account.id)

    if as_of_date is not None:
        query = query.join(models.Transaction).filter(models.Transaction.date <= as_of_date)

    result = query.first()

    total_debit = result.total_debit or 0.0
    total_credit = result.total_credit or 0.0

    if account.account_type in DEBIT_NORMAL_TYPES:
        return total_debit - total_credit
    return total_credit - total_debit


def _apply_debit(account: models.Account, amount: int, currency: str) -> None:
    # B5 will replace this cache; until then its unit remains major currency.
    major = Money(amount, currency).to_float()
    account.balance += signed_delta(account.account_type, debit=major, credit=0.0)


def _apply_credit(account: models.Account, amount: int, currency: str) -> None:
    major = Money(amount, currency).to_float()
    account.balance += signed_delta(account.account_type, debit=0.0, credit=major)


def _post_transaction_journal(
    db: Session,
    transaction: models.Transaction,
    legs: Sequence | None = None,
    *,
    from_account_id: int | None = None,
    to_account_id: int | None = None,
) -> None:
    """Write a transaction's journal legs and move the cached balances.

    Either `legs`, for any number of them, or a from/to pair, which describes
    the two legs of an ordinary entry. The two sides must balance and come to
    the transaction amount.
    """
    client_id = transaction.client_id
    if client_id is None:
        raise ValueError("transaction.client_id is required")

    if legs is None:
        posted = simple_legs(transaction.amount_minor, from_account_id, to_account_id)
    else:
        posted = [coerce_leg(leg, transaction.currency) for leg in legs]
    validate_legs(posted, transaction.amount_minor)

    accounts: dict[int, models.Account] = {}
    for leg in posted:
        if leg.account_id not in accounts:
            account = _get_account_by_id(db, leg.account_id, client_id)
            if account is None:
                raise ValueError(f"Account {leg.account_id} not found for this client")
            accounts[leg.account_id] = account

    for leg in posted:
        account = accounts[leg.account_id]
        if leg.debit:
            _apply_debit(account, leg.debit, transaction.currency)
        else:
            _apply_credit(account, leg.credit, transaction.currency)

    for order, leg in enumerate(posted):
        db.add(models.JournalEntry(
            transaction_id=transaction.id,
            account_id=leg.account_id,
            debit_minor=leg.debit,
            credit_minor=leg.credit,
            memo=leg.memo,
            sort_order=order,
        ))


def process_transaction(
    db: Session,
    transaction: models.Transaction,
    legs: Sequence | None = None,
    *,
    from_account_id: int | None = None,
    to_account_id: int | None = None,
) -> None:
    """Process a transaction with double-entry bookkeeping and commit it."""
    _post_transaction_journal(
        db, transaction, legs, from_account_id=from_account_id, to_account_id=to_account_id
    )
    db.commit()


def post_transaction_journal(
    db: Session,
    transaction: models.Transaction,
    legs: Sequence | None = None,
    *,
    from_account_id: int | None = None,
    to_account_id: int | None = None,
) -> None:
    """Post a transaction with double-entry bookkeeping without committing."""
    _post_transaction_journal(
        db, transaction, legs, from_account_id=from_account_id, to_account_id=to_account_id
    )


def get_transaction(db: Session, client_id: int, transaction_id: int) -> models.Transaction | None:
    return db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.client_id == client_id,
    ).first()


def list_transactions(
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
        # Compound entries can touch accounts that from/to columns cannot name.
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


def create_transaction(
    db: Session,
    *,
    client_id: int,
    legs: Sequence | None = None,
    from_account_id: int | None = None,
    to_account_id: int | None = None,
    **columns: Any,
) -> models.Transaction:
    """Create the row and its legs together because journal legs are not optional.

    Does not commit; the caller owns the transaction boundary.
    """
    for name in columns:
        if name not in models.Transaction.__table__.columns:
            raise TypeError(f"Unknown keyword {name!r} for table transactions")
    Money(columns["amount_minor"], columns.get("currency", "JPY"))
    transaction = models.Transaction(client_id=client_id, **columns)
    db.add(transaction)
    db.flush()
    _post_transaction_journal(
        db,
        transaction,
        legs,
        from_account_id=from_account_id,
        to_account_id=to_account_id,
    )
    return transaction


# Reservations and other proposed entries wait here for a decision. Keeping
# them outside transactions means reports only ever see posted ledger entries.
def propose_transaction(
    db: Session,
    client_id: int,
    *,
    origin: str,
    date: date,
    description: str,
    amount_minor: int,
    legs: Sequence,
    currency: str = "JPY",
    origin_ref: dict | None = None,
    trigger_transaction_id: int | None = None,
    idempotency_key: str | None = None,
) -> models.TransactionProposal:
    Money(amount_minor, currency)
    proposed = [coerce_leg(leg, currency) for leg in legs]
    validate_legs(proposed, amount_minor)
    for account_id in {leg.account_id for leg in proposed}:
        if _get_account_by_id(db, account_id, client_id) is None:
            raise ValueError(f"Account {account_id} not found for this client")
    stored_legs = [asdict(leg) for leg in proposed]
    origin_ref = origin_ref if origin_ref is not None else {}
    if idempotency_key is None:
        # Same canonical JSON/SHA-256 as AI requests, kept local because L1
        # cannot import the higher-layer AI service.
        payload = json.dumps(
            {
                "origin": origin,
                "origin_ref": origin_ref,
                "date": date.isoformat(),
                # Existing proposals must keep matching after their storage units change.
                "amount": Money(amount_minor, currency).to_float(),
                "legs": [{
                    **leg,
                    "debit": Money(leg["debit"], currency).to_float(),
                    "credit": Money(leg["credit"], currency).to_float(),
                } for leg in stored_legs],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        idempotency_key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    existing = db.query(models.TransactionProposal).filter(
        models.TransactionProposal.client_id == client_id,
        models.TransactionProposal.idempotency_key == idempotency_key,
    ).first()
    if existing is not None:
        return existing
    proposal = models.TransactionProposal(
        client_id=client_id,
        origin=origin,
        origin_ref=origin_ref,
        date=date,
        description=description,
        amount_minor=amount_minor,
        currency=currency,
        legs=stored_legs,
        trigger_transaction_id=trigger_transaction_id,
        idempotency_key=idempotency_key,
    )
    db.add(proposal)
    db.flush()
    return proposal


def approve_proposal(
    db: Session,
    proposal: models.TransactionProposal,
    *,
    actor_client_id: int,
) -> models.Transaction:
    if proposal.status != "pending":
        raise ValueError(f"Proposal {proposal.id} is not pending (status: {proposal.status})")
    transaction = create_transaction(
        db,
        client_id=proposal.client_id,
        date=proposal.date,
        description=proposal.description,
        amount_minor=proposal.amount_minor,
        currency=proposal.currency,
        legs=[Leg(**leg) for leg in proposal.legs],
    )
    proposal.status = "posted"
    proposal.posted_transaction_id = transaction.id
    proposal.decided_at = datetime.utcnow()
    proposal.decided_by_client_id = actor_client_id
    return transaction


def reject_proposal(
    db: Session,
    proposal: models.TransactionProposal,
    *,
    actor_client_id: int,
    note: str | None = None,
) -> None:
    if proposal.status != "pending":
        raise ValueError(f"Proposal {proposal.id} is not pending (status: {proposal.status})")
    proposal.status = "rejected"
    proposal.note = note
    proposal.decided_at = datetime.utcnow()
    proposal.decided_by_client_id = actor_client_id


def get_proposal(db: Session, client_id: int, proposal_id: int) -> models.TransactionProposal | None:
    return db.query(models.TransactionProposal).filter(
        models.TransactionProposal.id == proposal_id,
        models.TransactionProposal.client_id == client_id,
    ).first()


def list_proposals(
    db: Session,
    client_id: int,
    *,
    status: str | None = None,
    origin: str | None = None,
) -> list[models.TransactionProposal]:
    query = db.query(models.TransactionProposal).filter(
        models.TransactionProposal.client_id == client_id,
    )
    if status is not None:
        query = query.filter(models.TransactionProposal.status == status)
    if origin is not None:
        query = query.filter(models.TransactionProposal.origin == origin)
    return query.order_by(
        models.TransactionProposal.created_at.desc(),
        models.TransactionProposal.id.desc(),
    ).all()


def _rollback_transaction_effects(db: Session, transaction: models.Transaction) -> None:
    """Revert a transaction's impact on the cached balances, without committing.

    Each leg is reversed on its own account. Reading the legs rather than the
    header's two accounts is what makes this correct for a compound entry,
    where there are more than two of them and the header amount belongs to
    none of them individually.
    """
    client_id = transaction.client_id
    if client_id is None:
        return

    entries = db.query(models.JournalEntry).filter(
        models.JournalEntry.transaction_id == transaction.id,
    ).all()
    for entry in entries:
        account = _get_account_by_id(db, entry.account_id, client_id)
        if not account:
            continue
        if entry.debit_minor:
            _apply_credit(account, entry.debit_minor, transaction.currency)
        if entry.credit_minor:
            _apply_debit(account, entry.credit_minor, transaction.currency)


def revert_transaction(
    db: Session,
    transaction: models.Transaction,
    *,
    commit: bool = True,
) -> None:
    """Revert the impact of a transaction on account balances before deletion."""
    _rollback_transaction_effects(db, transaction)
    if commit:
        db.commit()


def delete_transaction(db: Session, transaction: models.Transaction) -> None:
    """Reverse balances before removing the legs that describe their effects.

    Balance reversal, leg deletion, and row deletion belong together to preserve
    ledger consistency. The caller owns the transaction boundary; this does not commit.
    """
    _rollback_transaction_effects(db, transaction)
    db.query(models.JournalEntry).filter(
        models.JournalEntry.transaction_id == transaction.id
    ).delete()
    db.delete(transaction)


def update_transaction(
    db: Session,
    transaction_id: int,
    payload,
    client_id: int,
    *,
    commit: bool = True,
) -> models.Transaction | None:
    tx = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.client_id == client_id,
    ).first()
    if not tx:
        return None

    try:
        prior = [
            Leg(
                account_id=entry.account_id,
                debit=entry.debit_minor,
                credit=entry.credit_minor,
                memo=entry.memo,
            )
            for entry in db.query(models.JournalEntry)
            .filter(models.JournalEntry.transaction_id == transaction_id)
            .order_by(models.JournalEntry.sort_order, models.JournalEntry.id)
            .all()
        ]

        _rollback_transaction_effects(db, tx)
        db.query(models.JournalEntry).filter(
            models.JournalEntry.transaction_id == transaction_id
        ).delete(synchronize_session=False)

        update_data = payload.model_dump(exclude_unset=True)
        legs = update_data.pop("legs", None)
        given_from = update_data.pop("from_account_id", None)
        given_to = update_data.pop("to_account_id", None)
        currency = update_data.get("currency", tx.currency)
        # Changing currency preserves the major amount, including retained compound legs.
        if "amount" in update_data or currency != tx.currency:
            amount = update_data.pop("amount", Money(tx.amount_minor, tx.currency).to_major())
            tx.amount_minor = Money.from_major(str(amount), currency).minor
        if currency != tx.currency:
            prior = [coerce_leg({
                "account_id": leg.account_id,
                "debit": Money(leg.debit, tx.currency).to_major(),
                "credit": Money(leg.credit, tx.currency).to_major(),
                "memo": leg.memo,
            }, currency) for leg in prior]
        for field, value in update_data.items():
            setattr(tx, field, value)

        if legs is None:
            # Neither legs nor a full pair of accounts: keep the accounts the
            # entry already had. A two-sided entry is rebuilt at the new
            # amount; a compound one keeps its legs, so changing only its
            # amount is refused by the balance check rather than silently
            # reshaped.
            prior_credits = [leg for leg in prior if leg.credit > 0]
            prior_debits = [leg for leg in prior if leg.debit > 0]
            resolved_from = given_from if given_from is not None else (
                prior_credits[0].account_id if len(prior_credits) == 1 else None
            )
            resolved_to = given_to if given_to is not None else (
                prior_debits[0].account_id if len(prior_debits) == 1 else None
            )
            if resolved_from is not None and resolved_to is not None:
                legs = simple_legs(tx.amount_minor, resolved_from, resolved_to)
            else:
                legs = prior

        db.flush()
        _post_transaction_journal(db, tx, legs)
        if commit:
            db.commit()
            db.refresh(tx)
        return tx
    except Exception:
        db.rollback()
        raise
