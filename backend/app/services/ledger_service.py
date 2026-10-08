"""Ledger Service - double-entry bookkeeping primitives.

Layer 1. Owns transaction posting, journal entries and account balance
mutation. Depends on nothing but the ORM models: never on planning,
registry or reporting.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

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


def _resolve_account(
    db: Session,
    client_id: int,
    account_id: Optional[int],
    fallback_name: str,
    fallback_type: str,
) -> models.Account:
    by_id = _get_account_by_id(db, account_id, client_id)
    if by_id:
        return by_id

    return get_or_create_account(db, fallback_name, client_id, fallback_type, commit=False)


DEBIT_NORMAL_TYPES = {"asset", "expense", "item"}


TRANSACTION_ACCOUNT_DEFAULTS = {
    "Income": {
        "from_name": "salary",
        "from_type": "income",
        "to_name": "cash",
        "to_type": "asset",
    },
    "Expense": {
        "from_name": "cash",
        "from_type": "asset",
        "to_name": "expense",
        "to_type": "expense",
    },
    "Transfer": {
        "from_name": "cash",
        "from_type": "asset",
        "to_name": "savings",
        "to_type": "asset",
    },
    "LiabilityPayment": {
        "from_name": "cash",
        "from_type": "asset",
        "to_name": "loan",
        "to_type": "liability",
    },
    "Borrowing": {
        "from_name": "loan",
        "from_type": "liability",
        "to_name": "cash",
        "to_type": "asset",
    },
    "CreditExpense": {
        "from_name": "credit",
        "from_type": "liability",
        "to_name": "expense",
        "to_type": "expense",
    },
    "CreditAssetPurchase": {
        "from_name": "credit",
        "from_type": "liability",
        "to_name": "savings",
        "to_type": "asset",
    },
}


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


def _post_transaction_journal(db: Session, transaction: models.Transaction) -> None:
    """
    Post a transaction with double-entry bookkeeping without committing.
    The UI uses from_account as the credit side and to_account as the debit side.
    """
    client_id = transaction.client_id
    if client_id is None:
        raise ValueError("transaction.client_id is required")

    category = transaction.category or "expense"
    defaults = TRANSACTION_ACCOUNT_DEFAULTS.get(transaction.type)
    if not defaults:
        raise ValueError(f"Unsupported transaction type: {transaction.type}")

    from_fallback_name = category if transaction.type == "Income" else defaults["from_name"]
    to_fallback_name = category if transaction.type in ("Expense", "CreditExpense") else defaults["to_name"]

    from_account = _resolve_account(
        db=db,
        client_id=client_id,
        account_id=transaction.from_account_id,
        fallback_name=from_fallback_name,
        fallback_type=defaults["from_type"],
    )
    to_account = _resolve_account(
        db=db,
        client_id=client_id,
        account_id=transaction.to_account_id,
        fallback_name=to_fallback_name,
        fallback_type=defaults["to_type"],
    )

    _apply_credit(from_account, transaction.amount)
    _apply_debit(to_account, transaction.amount)

    # Persist resolved account linkage for read APIs.
    transaction.from_account_id = from_account.id
    transaction.to_account_id = to_account.id

    debit_entry = models.JournalEntry(
        transaction_id=transaction.id,
        account_id=to_account.id,
        debit=transaction.amount,
        credit=0,
    )
    credit_entry = models.JournalEntry(
        transaction_id=transaction.id,
        account_id=from_account.id,
        debit=0,
        credit=transaction.amount,
    )

    db.add(debit_entry)
    db.add(credit_entry)


def process_transaction(db: Session, transaction: models.Transaction) -> None:
    """Process a transaction with double-entry bookkeeping and commit it."""
    _post_transaction_journal(db, transaction)
    db.commit()


def post_transaction_journal(db: Session, transaction: models.Transaction) -> None:
    """Post a transaction with double-entry bookkeeping without committing."""
    _post_transaction_journal(db, transaction)


def _rollback_transaction_effects(db: Session, transaction: models.Transaction) -> None:
    """
    Revert the impact of a transaction on account balances without committing.
    """
    client_id = transaction.client_id
    if client_id is None:
        return

    from_account = _get_account_by_id(db, transaction.from_account_id, client_id)
    to_account = _get_account_by_id(db, transaction.to_account_id, client_id)

    if from_account:
        _apply_debit(from_account, transaction.amount)
    if to_account:
        _apply_credit(to_account, transaction.amount)


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
        _rollback_transaction_effects(db, tx)
        db.query(models.JournalEntry).filter(
            models.JournalEntry.transaction_id == transaction_id
        ).delete(synchronize_session=False)

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(tx, field, value)

        # Keep category in sync with to_account when account changes for expense types.
        if 'to_account_id' in update_data and 'category' not in update_data:
            if tx.type in ("Expense", "CreditExpense") and tx.to_account_id:
                to_acct = _get_account_by_id(db, tx.to_account_id, client_id)
                if to_acct:
                    tx.category = to_acct.name

        db.flush()
        _post_transaction_journal(db, tx)
        db.commit()
        db.refresh(tx)
        return tx
    except Exception:
        db.rollback()
        raise
