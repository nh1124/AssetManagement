from __future__ import annotations

from datetime import date

import httpx
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .. import models

DEBIT_NORMAL_TYPES = {"asset", "expense", "item"}
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"


def normalize_currency(currency: str | None) -> str:
    return (currency or "JPY").strip().upper() or "JPY"


def get_client_currency(db: Session, client_id: int | None) -> str:
    if client_id is None:
        return "JPY"
    client = db.query(models.Client).filter(models.Client.id == client_id).first()
    settings = client.general_settings if client and client.general_settings else {}
    return normalize_currency(settings.get("currency") if isinstance(settings, dict) else None)


def _latest_rate(
    db: Session,
    client_id: int,
    base_currency: str,
    quote_currency: str,
    as_of_date: date | None,
) -> models.ExchangeRate | None:
    query = db.query(models.ExchangeRate).filter(
        models.ExchangeRate.client_id == client_id,
        models.ExchangeRate.base_currency == base_currency,
        models.ExchangeRate.quote_currency == quote_currency,
    )
    if as_of_date is not None:
        dated = query.filter(models.ExchangeRate.as_of_date <= as_of_date).order_by(
            desc(models.ExchangeRate.as_of_date),
            desc(models.ExchangeRate.id),
        ).first()
        if dated:
            return dated
    return query.order_by(desc(models.ExchangeRate.as_of_date), desc(models.ExchangeRate.id)).first()


def get_exchange_rate(
    db: Session,
    client_id: int,
    base_currency: str,
    quote_currency: str,
    as_of_date: date | None = None,
) -> float | None:
    base = normalize_currency(base_currency)
    quote = normalize_currency(quote_currency)
    if base == quote:
        return 1.0

    direct = _latest_rate(db, client_id, base, quote, as_of_date)
    if direct and direct.rate:
        return direct.rate

    inverse = _latest_rate(db, client_id, quote, base, as_of_date)
    if inverse and inverse.rate:
        return 1.0 / inverse.rate

    return None


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


def fetch_frankfurter_rate(base_currency: str, quote_currency: str) -> dict:
    base = normalize_currency(base_currency)
    quote = normalize_currency(quote_currency)
    if base == quote:
        return {"rate": 1.0, "market_date": date.today().isoformat(), "provider": "frankfurter"}

    response = httpx.get(
        FRANKFURTER_URL,
        params={"from": base, "to": quote},
        timeout=10.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    payload = response.json()
    rate = (payload.get("rates") or {}).get(quote)
    if not rate:
        raise ValueError(f"No rate returned for {base}/{quote}")
    return {
        "rate": float(rate),
        "market_date": payload.get("date") or date.today().isoformat(),
        "provider": "frankfurter",
    }


def upsert_exchange_rate(
    db: Session,
    client_id: int,
    base_currency: str,
    quote_currency: str,
    rate: float,
    as_of_date: date,
    source: str,
) -> models.ExchangeRate:
    base = normalize_currency(base_currency)
    quote = normalize_currency(quote_currency)
    existing = db.query(models.ExchangeRate).filter(
        models.ExchangeRate.client_id == client_id,
        models.ExchangeRate.base_currency == base,
        models.ExchangeRate.quote_currency == quote,
        models.ExchangeRate.as_of_date == as_of_date,
    ).first()
    if existing:
        existing.rate = rate
        existing.source = source
        db.flush()
        return existing

    row = models.ExchangeRate(
        client_id=client_id,
        base_currency=base,
        quote_currency=quote,
        rate=rate,
        as_of_date=as_of_date,
        source=source,
    )
    db.add(row)
    db.flush()
    return row


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


def convert_amount(
    db: Session,
    client_id: int | None,
    amount: float | None,
    from_currency: str | None,
    to_currency: str | None = None,
    as_of_date: date | None = None,
) -> float:
    source = normalize_currency(from_currency)
    target = normalize_currency(to_currency) if to_currency else get_client_currency(db, client_id)
    value = amount or 0.0
    if source == target:
        return value
    if client_id is None:
        return value
    rate = get_exchange_rate(db, client_id, source, target, as_of_date)
    if rate is None:
        # Never treat an unknown foreign-currency amount as if it were already
        # denominated in the base currency. The rate table is the valuation gate.
        return 0.0
    return value * rate


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


class RateLookup:
    """Small per-request FX lookup to avoid querying rates for every row."""

    def __init__(self, db: Session, client_id: int, target_currency: str):
        self.target_currency = normalize_currency(target_currency)
        rows = db.query(models.ExchangeRate).filter(
            models.ExchangeRate.client_id == client_id,
        ).order_by(
            models.ExchangeRate.base_currency,
            models.ExchangeRate.quote_currency,
            models.ExchangeRate.as_of_date,
            models.ExchangeRate.id,
        ).all()
        self._rates: dict[tuple[str, str], list[models.ExchangeRate]] = {}
        for row in rows:
            key = (normalize_currency(row.base_currency), normalize_currency(row.quote_currency))
            self._rates.setdefault(key, []).append(row)

    def _latest(self, base: str, quote: str, as_of_date: date | None) -> models.ExchangeRate | None:
        candidates = self._rates.get((base, quote), [])
        selected = None
        for row in candidates:
            if as_of_date is not None and row.as_of_date and row.as_of_date > as_of_date:
                continue
            selected = row
        if selected is not None:
            return selected
        return candidates[-1] if candidates else None

    def rate(self, base_currency: str | None, quote_currency: str | None, as_of_date: date | None) -> float | None:
        base = normalize_currency(base_currency)
        quote = normalize_currency(quote_currency)
        if base == quote:
            return 1.0

        direct = self._latest(base, quote, as_of_date)
        if direct and direct.rate:
            return direct.rate

        inverse = self._latest(quote, base, as_of_date)
        if inverse and inverse.rate:
            return 1.0 / inverse.rate

        return None

    def convert(self, amount: float | None, from_currency: str | None, as_of_date: date | None) -> float:
        value = amount or 0.0
        source = normalize_currency(from_currency)
        if source == self.target_currency:
            return value
        rate = self.rate(source, self.target_currency, as_of_date)
        if rate is None:
            return 0.0
        return value * rate


def build_rate_lookup(
    db: Session,
    client_id: int | None,
    target_currency: str | None = None,
) -> RateLookup | None:
    if client_id is None:
        return None
    target = normalize_currency(target_currency) if target_currency else get_client_currency(db, client_id)
    return RateLookup(db, client_id, target)


def convert_amount_with_lookup(
    lookup: RateLookup | None,
    amount: float | None,
    from_currency: str | None,
    as_of_date: date | None,
) -> float:
    if lookup is None:
        return amount or 0.0
    return lookup.convert(amount, from_currency, as_of_date)


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
