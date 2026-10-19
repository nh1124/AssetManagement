"""fx_service knows rates; this module knows what the ledger is worth and which
rates it needs. Separating those responsibilities lets fx_service remain a leaf.
"""
from __future__ import annotations

from datetime import date
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from .fx_service import (
    normalize_currency,
    get_client_currency,
    build_rate_lookup,
    convert_amount_with_lookup,
    convert_amount,
)
from .ledger_service import DEBIT_NORMAL_TYPES


def convert_transaction_amount(
    db: Session,
    transaction: models.Transaction,
    client_id: int | None = None,
    target_currency: str | None = None,
) -> float:
    owner_id = client_id if client_id is not None else transaction.client_id
    return convert_amount(
        db=db,
        client_id=owner_id,
        amount=transaction.amount,
        from_currency=transaction.currency,
        to_currency=target_currency,
        as_of_date=transaction.date,
    )


@dataclass
class AccountBalances:
    # Holdings retain their denominations exactly; valuation answers what those
    # holdings are worth for display and cannot replace them when FX rates move.
    balances_minor: dict[str, int] = field(default_factory=dict)
    balance: float = 0.0


def calculate_account_balances(
    db: Session,
    accounts: list[models.Account],
    as_of_date: date | None = None,
    target_currency: str | None = None,
) -> dict[int, AccountBalances]:
    """Calculate balances for many accounts with one journal query."""
    if not accounts:
        return {}

    account_by_id = {account.id: account for account in accounts}
    balances = {account.id: AccountBalances() for account in accounts}
    client_id = accounts[0].client_id
    lookup = build_rate_lookup(db, client_id, target_currency)

    query = db.query(models.JournalEntry, models.Transaction).join(
        models.Transaction,
        models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(models.JournalEntry.account_id.in_(account_by_id.keys()))

    if as_of_date is not None:
        query = query.filter(models.Transaction.date <= as_of_date)

    for entry, transaction in query.all():
        account = account_by_id.get(entry.account_id)
        if not account:
            continue
        if account.account_type in DEBIT_NORMAL_TYPES:
            signed_minor = entry.debit_minor - entry.credit_minor
        else:
            signed_minor = entry.credit_minor - entry.debit_minor
        currency = normalize_currency(transaction.currency)
        result = balances[account.id]
        result.balances_minor[currency] = result.balances_minor.get(currency, 0) + signed_minor
        result.balance += convert_amount_with_lookup(
            lookup,
            Money(signed_minor, currency).to_float(),
            currency,
            transaction.date,
        )

    return balances


def calculate_account_valued_balances(
    db: Session,
    accounts: list[models.Account],
    as_of_date: date | None = None,
    target_currency: str | None = None,
) -> dict[int, float]:
    return {account_id: result.balance for account_id, result in
            calculate_account_balances(db, accounts, as_of_date, target_currency).items()}


def calculate_account_valued_balance(
    db: Session,
    account: models.Account,
    as_of_date: date | None = None,
    target_currency: str | None = None,
) -> float:
    return calculate_account_valued_balances(db, [account], as_of_date, target_currency).get(account.id, 0.0)
