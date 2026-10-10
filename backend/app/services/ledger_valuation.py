"""fx_service knows rates; this module knows what the ledger is worth and which
rates it needs. Separating those responsibilities lets fx_service remain a leaf.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from .fx_service import (
    normalize_currency,
    get_client_currency,
    build_rate_lookup,
    convert_amount_with_lookup,
    convert_amount,
    upsert_exchange_rate,
    fetch_frankfurter_rate,
)
from .ledger_service import DEBIT_NORMAL_TYPES


def get_used_currency_pairs(
    db: Session,
    client_id: int,
    quote_currency: str | None = None,
) -> list[dict[str, str]]:
    quote = normalize_currency(quote_currency) if quote_currency else get_client_currency(db, client_id)
    currencies = db.query(models.Transaction.currency).filter(
        models.Transaction.client_id == client_id,
        models.Transaction.currency.isnot(None),
    ).distinct().all()

    pairs = []
    seen = set()
    for (currency,) in currencies:
        base = normalize_currency(currency)
        if base == quote:
            continue
        key = (base, quote)
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"base_currency": base, "quote_currency": quote})
    return pairs


def update_used_exchange_rates(
    db: Session,
    client_id: int,
    today: date | None = None,
    fetcher=fetch_frankfurter_rate,
) -> dict:
    valuation_date = today or date.today()
    pairs = get_used_currency_pairs(db, client_id)
    updated = []
    skipped = []
    errors = []

    for pair in pairs:
        base = pair["base_currency"]
        quote = pair["quote_currency"]
        existing_today = db.query(models.ExchangeRate).filter(
            models.ExchangeRate.client_id == client_id,
            models.ExchangeRate.base_currency == base,
            models.ExchangeRate.quote_currency == quote,
            models.ExchangeRate.as_of_date == valuation_date,
        ).first()
        if existing_today:
            skipped.append({
                "base_currency": base,
                "quote_currency": quote,
                "reason": "already_updated_today",
            })
            continue

        try:
            fetched = fetcher(base, quote)
            row = upsert_exchange_rate(
                db=db,
                client_id=client_id,
                base_currency=base,
                quote_currency=quote,
                rate=fetched["rate"],
                as_of_date=valuation_date,
                source=f"auto:{fetched.get('provider', 'unknown')}:{fetched.get('market_date', valuation_date.isoformat())}",
            )
            updated.append({
                "id": row.id,
                "base_currency": row.base_currency,
                "quote_currency": row.quote_currency,
                "rate": row.rate,
                "as_of_date": row.as_of_date.isoformat(),
                "source": row.source,
            })
        except Exception as exc:
            errors.append({
                "base_currency": base,
                "quote_currency": quote,
                "error": str(exc),
            })

    db.commit()
    return {
        "target_currency": get_client_currency(db, client_id),
        "detected_pairs": pairs,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


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


def calculate_account_valued_balances(
    db: Session,
    accounts: list[models.Account],
    as_of_date: date | None = None,
    target_currency: str | None = None,
) -> dict[int, float]:
    """Calculate balances for many accounts with one journal query."""
    if not accounts:
        return {}

    account_by_id = {account.id: account for account in accounts}
    balances = {account.id: 0.0 for account in accounts}
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
            signed_amount = (entry.debit or 0.0) - (entry.credit or 0.0)
        else:
            signed_amount = (entry.credit or 0.0) - (entry.debit or 0.0)
        balances[account.id] += convert_amount_with_lookup(
            lookup,
            signed_amount,
            transaction.currency,
            transaction.date,
        )

    return balances


def calculate_account_valued_balance(
    db: Session,
    account: models.Account,
    as_of_date: date | None = None,
    target_currency: str | None = None,
) -> float:
    return calculate_account_valued_balances(db, [account], as_of_date, target_currency).get(account.id, 0.0)
