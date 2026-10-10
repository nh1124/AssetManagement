"""Ledger Service - double-entry bookkeeping primitives.

Layer 1. Owns transaction posting, journal entries and account balance
mutation. Depends on nothing but the ORM models: never on planning,
registry or reporting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models


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


DEBIT_NORMAL_TYPES = {"asset", "expense", "item"}


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


def _apply_debit(account: models.Account, amount: float) -> None:
    if account.account_type in DEBIT_NORMAL_TYPES:
        account.balance += amount
    else:
        account.balance -= amount


def _apply_credit(account: models.Account, amount: float) -> None:
    if account.account_type in DEBIT_NORMAL_TYPES:
        account.balance -= amount
    else:
        account.balance += amount


BALANCE_TOLERANCE = 0.01


@dataclass(frozen=True)
class Leg:
    """One side of an entry, as given to the posting code."""

    account_id: int
    debit: float = 0.0
    credit: float = 0.0
    memo: str | None = None


def _coerce_leg(leg) -> Leg:
    """Accept a Leg, a pydantic model or a plain mapping."""
    if isinstance(leg, Leg):
        return leg
    if isinstance(leg, dict):
        data = leg
    else:
        data = {
            "account_id": getattr(leg, "account_id", None),
            "debit": getattr(leg, "debit", 0.0),
            "credit": getattr(leg, "credit", 0.0),
            "memo": getattr(leg, "memo", None),
        }
    return Leg(
        account_id=data.get("account_id"),
        debit=float(data.get("debit") or 0.0),
        credit=float(data.get("credit") or 0.0),
        memo=data.get("memo"),
    )


def _validate_legs(legs: list[Leg], amount: float) -> None:
    """The ledger invariant, in one place.

    Two or more legs, each on exactly one side, and both sides summing to the
    transaction amount. The amount is a denormalisation of the legs, so it
    doubles as the checksum: a receipt total that disagrees with its breakdown
    is a mistake, not a rounding difference.
    """
    if len(legs) < 2:
        raise ValueError("A journal entry needs at least two legs")

    for leg in legs:
        if not leg.account_id:
            raise ValueError("Every journal leg needs an account")
        if leg.debit < 0 or leg.credit < 0:
            raise ValueError("Journal legs cannot be negative")
        if (leg.debit > 0) == (leg.credit > 0):
            raise ValueError("A journal leg is either a debit or a credit, not both or neither")

    total_debit = sum(leg.debit for leg in legs)
    total_credit = sum(leg.credit for leg in legs)
    if abs(total_debit - total_credit) > BALANCE_TOLERANCE:
        raise ValueError(
            f"Journal entry does not balance: debit {total_debit} vs credit {total_credit}"
        )
    if abs(total_debit - (amount or 0.0)) > BALANCE_TOLERANCE:
        raise ValueError(
            f"Journal entry total {total_debit} does not match the transaction amount {amount}"
        )


def simple_legs(
    amount: float | None,
    from_account_id: int | None,
    to_account_id: int | None,
) -> list[Leg]:
    """The two legs a from/to pair describes.

    from_account is the credit side and to_account the debit side, which is the
    direction the API and the UI have always used. Both are required: there is
    nothing left to infer a missing account from, and inferring one is how
    transactions used to land on whichever account happened to come first.
    The accounts themselves are checked where every leg is.
    """
    if from_account_id is None or to_account_id is None:
        raise ValueError(
            "A transaction needs both from_account_id and to_account_id, or explicit legs"
        )
    total = amount or 0.0
    return [
        Leg(account_id=to_account_id, debit=total),
        Leg(account_id=from_account_id, credit=total),
    ]


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
        posted = simple_legs(transaction.amount, from_account_id, to_account_id)
    else:
        posted = [_coerce_leg(leg) for leg in legs]
    _validate_legs(posted, transaction.amount or 0.0)

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
            _apply_debit(account, leg.debit)
        else:
            _apply_credit(account, leg.credit)

    for order, leg in enumerate(posted):
        db.add(models.JournalEntry(
            transaction_id=transaction.id,
            account_id=leg.account_id,
            debit=leg.debit,
            credit=leg.credit,
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
        if entry.debit:
            _apply_credit(account, entry.debit)
        if entry.credit:
            _apply_debit(account, entry.credit)


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
                debit=entry.debit or 0.0,
                credit=entry.credit or 0.0,
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
                legs = simple_legs(tx.amount, resolved_from, resolved_to)
            else:
                legs = prior

        db.flush()
        _post_transaction_journal(db, tx, legs)
        db.commit()
        db.refresh(tx)
        return tx
    except Exception:
        db.rollback()
        raise
