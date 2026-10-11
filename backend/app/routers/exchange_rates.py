from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.fx_service import delete_rate, list_rates, normalize_currency, update_rate, upsert_exchange_rate
from ..services.ledger_valuation import update_used_exchange_rates

router = APIRouter(prefix="/exchange-rates", tags=["exchange_rates"])


def _serialize(rate: models.ExchangeRate) -> dict:
    return {
        "id": rate.id,
        "base_currency": rate.base_currency,
        "quote_currency": rate.quote_currency,
        "rate": rate.rate,
        "as_of_date": rate.as_of_date,
        "source": rate.source,
        "created_at": rate.created_at,
        "updated_at": rate.updated_at,
    }


@router.get("/", response_model=list[schemas.ExchangeRate])
def get_exchange_rates(
    base_currency: Optional[str] = Query(None),
    quote_currency: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    rates = list_rates(db, current_client.id, base_currency, quote_currency)
    return [_serialize(rate) for rate in rates]


@router.post("/auto-update")
def auto_update_exchange_rates(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Fetch today's rates for currencies actually used in journal transactions."""
    result = update_used_exchange_rates(db, current_client.id)
    invalidate_client(current_client.id)
    return result


@router.post("/", response_model=schemas.ExchangeRate)
def create_exchange_rate(
    payload: schemas.ExchangeRateCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    base = normalize_currency(payload.base_currency)
    quote = normalize_currency(payload.quote_currency)
    if base == quote:
        raise HTTPException(status_code=400, detail="Currencies must differ")

    rate = upsert_exchange_rate(
        db,
        current_client.id,
        base_currency=base,
        quote_currency=quote,
        rate=payload.rate,
        as_of_date=payload.as_of_date,
        source=payload.source or "manual",
        commit=True,
    )
    invalidate_client(current_client.id)
    return _serialize(rate)


@router.put("/{rate_id}", response_model=schemas.ExchangeRate)
def update_exchange_rate(
    rate_id: int,
    payload: schemas.ExchangeRateUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    rate = update_rate(db, current_client.id, rate_id, payload)
    if rate is None:
        raise HTTPException(status_code=404, detail="Exchange rate not found")
    invalidate_client(current_client.id)
    return _serialize(rate)


@router.delete("/{rate_id}")
def delete_exchange_rate(
    rate_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not delete_rate(db, current_client.id, rate_id):
        raise HTTPException(status_code=404, detail="Exchange rate not found")
    invalidate_client(current_client.id)
    return {"message": "Exchange rate deleted"}
