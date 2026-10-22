"""Tracking validates a quote before saving; refresh isolates failed currencies."""
from __future__ import annotations

from datetime import date
import logging
import math

from sqlalchemy.orm import Session

from ..domain.errors import Invalid, NotFound
from ..services import fx_service as fx
from ..services.cache_service import invalidate_client

logger = logging.getLogger(__name__)


def _fetch(currency: str, target: str) -> dict:
    try:
        fetched = fx.fetch_frankfurter_rate(currency, target)
        rate = float(fetched["rate"])
        market_date = date.fromisoformat(fetched["market_date"])
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("invalid rate")
        return {"rate": rate, "as_of_date": market_date, "source": fetched["provider"]}
    except Exception as exc:
        raise Invalid(f"{currency} のレートを取得できませんでした", en=f"Could not fetch the {currency} rate") from exc


def track(db: Session, client_id: int, currency: str):
    code = fx.normalize_currency(currency)
    target = fx.get_client_currency(db, client_id)
    if code == target:
        raise Invalid("基準通貨は追跡できません", en="The base currency cannot be tracked")
    fetched = _fetch(code, target)
    try:
        row = fx.add_tracked(db, client_id, code)
        fx.upsert_exchange_rate(db, client_id, code, target, **fetched)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return row


def untrack(db: Session, client_id: int, currency: str) -> None:
    if not fx.remove_tracked(db, client_id, currency):
        raise NotFound("追跡通貨がありません", en="This currency is not tracked")
    db.commit()


def delete_rate(db: Session, client_id: int, rate_id: int) -> None:
    if not fx.delete_rate(db, client_id, rate_id):
        raise NotFound("為替レートがありません", en="Exchange rate not found")
    db.commit()
    invalidate_client(client_id)


def refresh(db: Session, client_id: int) -> dict:
    target = fx.get_client_currency(db, client_id)
    currencies = [row.currency for row in fx.list_tracked(db, client_id)]
    updated, errors = [], []
    for currency in currencies:
        # A settings change can make a tracked currency the base currency.
        if currency == target:
            continue
        try:
            fetched = _fetch(currency, target)
            row = fx.upsert_exchange_rate(db, client_id, currency, target, **fetched)
            result = {"id": row.id, "base_currency": currency, "quote_currency": target,
                      "rate": row.rate, "as_of_date": row.as_of_date.isoformat(), "source": row.source}
            db.commit()
            updated.append(result)
        except Exception as exc:
            db.rollback()
            logger.exception("FX refresh failed: client=%s currency=%s", client_id, currency)
            errors.append({"base_currency": currency, "quote_currency": target, "error": str(exc)})
    if updated:
        invalidate_client(client_id)
    return {"target_currency": target, "updated": updated, "errors": errors}


def refresh_all(db: Session) -> None:
    for client_id in fx.tracked_clients(db):
        try:
            refresh(db, client_id)
        except Exception:
            db.rollback()
            logger.exception("FX client refresh failed: client=%s", client_id)
