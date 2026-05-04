from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.fx_service import normalize_currency, update_used_exchange_rates

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
    query = db.query(models.ExchangeRate).filter(
        models.ExchangeRate.client_id == current_client.id
    )
    if base_currency:
        query = query.filter(models.ExchangeRate.base_currency == normalize_currency(base_currency))
    if quote_currency:
        query = query.filter(models.ExchangeRate.quote_currency == normalize_currency(quote_currency))
    rates = query.order_by(
        models.ExchangeRate.base_currency,
        models.ExchangeRate.quote_currency,
        models.ExchangeRate.as_of_date.desc(),
    ).all()
    return [_serialize(rate) for rate in rates]


@router.post("/auto-update")
def auto_update_exchange_rates(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Fetch today's rates for currencies actually used in journal transactions."""
    return update_used_exchange_rates(db, current_client.id)


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

    existing = db.query(models.ExchangeRate).filter(
        models.ExchangeRate.client_id == current_client.id,
        models.ExchangeRate.base_currency == base,
        models.ExchangeRate.quote_currency == quote,
        models.ExchangeRate.as_of_date == payload.as_of_date,
    ).first()
    if existing:
        existing.rate = payload.rate
        existing.source = payload.source or "manual"
        db.commit()
        db.refresh(existing)
        return _serialize(existing)

    rate = models.ExchangeRate(
        client_id=current_client.id,
        base_currency=base,
        quote_currency=quote,
        rate=payload.rate,
        as_of_date=payload.as_of_date,
        source=payload.source or "manual",
    )
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return _serialize(rate)


@router.put("/{rate_id}", response_model=schemas.ExchangeRate)
def update_exchange_rate(
    rate_id: int,
    payload: schemas.ExchangeRateUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    rate = db.query(models.ExchangeRate).filter(
        models.ExchangeRate.id == rate_id,
        models.ExchangeRate.client_id == current_client.id,
    ).first()
    if not rate:
        raise HTTPException(status_code=404, detail="Exchange rate not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("base_currency", "quote_currency"):
            value = normalize_currency(value)
        setattr(rate, field, value)
    if rate.base_currency == rate.quote_currency:
        raise HTTPException(status_code=400, detail="Currencies must differ")
    db.commit()
    db.refresh(rate)
    return _serialize(rate)


@router.delete("/{rate_id}")
def delete_exchange_rate(
    rate_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    rate = db.query(models.ExchangeRate).filter(
        models.ExchangeRate.id == rate_id,
        models.ExchangeRate.client_id == current_client.id,
    ).first()
    if not rate:
        raise HTTPException(status_code=404, detail="Exchange rate not found")
    db.delete(rate)
    db.commit()
    return {"message": "Exchange rate deleted"}
