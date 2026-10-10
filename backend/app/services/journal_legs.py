"""Reading the ledger one leg at a time.

A transaction used to be its own summary: `type` said what kind of movement it
was, `from_account_id` and `to_account_id` said which two accounts it touched,
and `amount` applied to both of them. That summary only holds while every
transaction has exactly two legs. A meal paid by card where part of the bill
was fronted for someone else has three -- the card on one side, an expense
account and a receivable on the other -- and there is no single `to_account`
and no single kind.

So aggregation reads `journal_entries` instead. Each leg says which account it
touched, in which direction, for how much; the account's own type says what
that means. The expense side of a split lands in the P/L, the receivable side
does not, and nothing has to know that the transaction was "a card expense".

Amounts here are valued in the client's currency. FX lives on the transaction
(its currency and date), so a leg is scaled by the same factor as its parent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .. import models
from .ledger_valuation import convert_transaction_amount
from .ledger_service import DEBIT_NORMAL_TYPES
from .periods import period_to_range


@dataclass(frozen=True)
class Leg:
    """One journal entry with its transaction and account already resolved."""

    entry: models.JournalEntry
    transaction: models.Transaction
    account: models.Account
    debit: float
    credit: float

    @property
    def raw_debit(self) -> float:
        return self.entry.debit or 0.0

    @property
    def raw_credit(self) -> float:
        return self.entry.credit or 0.0

    @property
    def account_type(self) -> str | None:
        return self.account.account_type

    @property
    def signed(self) -> float:
        """The movement in the account's own normal direction."""
        return signed_delta(self.account.account_type, self.debit, self.credit)

    @property
    def is_debit(self) -> bool:
        return self.raw_debit > 0


def primary_accounts(
    transaction: models.Transaction,
) -> tuple[models.Account | None, models.Account | None]:
    """The (from, to) accounts an entry can be summarised by, or None a side.

    from is the credited account and to the debited one, which is the direction
    the API and the UI have always used. A side with more than one leg has no
    single account, and saying so is the point: a three-leg meal has no one
    destination, and the legs are right there in the same payload.
    """
    entries = list(transaction.journal_entries or [])
    credits = [entry for entry in entries if (entry.credit or 0.0) > 0]
    debits = [entry for entry in entries if (entry.debit or 0.0) > 0]
    return (
        credits[0].account if len(credits) == 1 else None,
        debits[0].account if len(debits) == 1 else None,
    )


def signed_delta(account_type: str | None, debit: float, credit: float) -> float:
    if account_type in DEBIT_NORMAL_TYPES:
        return debit - credit
    return credit - debit


def valued_sides(db: Session, entry: models.JournalEntry, tx: models.Transaction, client_id: int | None) -> tuple[float, float]:
    """A leg's debit and credit in the client's currency."""
    raw_debit = entry.debit or 0.0
    raw_credit = entry.credit or 0.0
    if not tx.amount:
        return raw_debit, raw_credit
    factor = convert_transaction_amount(db, tx, client_id=client_id) / tx.amount
    return raw_debit * factor, raw_credit * factor


def legs_in_range(
    db: Session,
    client_id: int | None,
    start_date: date,
    end_date: date,
    *,
    account_types: set[str] | None = None,
    account_ids: set[int] | None = None,
) -> list[Leg]:
    """Every leg of the client's transactions in an inclusive date range.

    One query with the accounts joined, because the callers all need the
    account type to know what a leg means.
    """
    query = (
        db.query(models.JournalEntry, models.Transaction, models.Account)
        .join(models.Transaction, models.Transaction.id == models.JournalEntry.transaction_id)
        .join(models.Account, models.Account.id == models.JournalEntry.account_id)
        .filter(
            models.Transaction.client_id == client_id,
            models.Transaction.date >= start_date,
            models.Transaction.date <= end_date,
        )
    )
    if account_types:
        query = query.filter(models.Account.account_type.in_(account_types))
    if account_ids is not None:
        if not account_ids:
            return []
        query = query.filter(models.JournalEntry.account_id.in_(account_ids))

    legs: list[Leg] = []
    for entry, tx, account in query.all():
        debit, credit = valued_sides(db, entry, tx, client_id)
        legs.append(Leg(entry=entry, transaction=tx, account=account, debit=debit, credit=credit))
    return legs


def legs_in_period(
    db: Session,
    client_id: int | None,
    period: str,
    *,
    account_types: set[str] | None = None,
    account_ids: set[int] | None = None,
) -> list[Leg]:
    """Every leg in a "YYYY-MM" month. period_to_range returns an open end."""
    start, end = period_to_range(period)
    return legs_in_range(
        db,
        client_id,
        start,
        end - timedelta(days=1),
        account_types=account_types,
        account_ids=account_ids,
    )
