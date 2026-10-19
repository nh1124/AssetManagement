from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.fx_service import list_rates, list_tracked
from ..workflows import fx_workflow

router = APIRouter(prefix="/exchange-rates", tags=["exchange_rates"])


@router.get("/", response_model=list[schemas.ExchangeRate])
def get_exchange_rates(
    base_currency: str | None = Query(None), quote_currency: str | None = Query(None),
    db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client),
):
    return list_rates(db, current_client.id, base_currency, quote_currency)


@router.get("/tracked", response_model=list[schemas.FxTrackedCurrency])
def get_tracked_currencies(db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return list_tracked(db, current_client.id)


@router.post("/tracked", response_model=schemas.FxTrackedCurrency)
def track_currency(payload: schemas.FxTrackedCurrencyCreate, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return fx_workflow.track(db, current_client.id, payload.currency)


@router.delete("/tracked/{currency}")
def untrack_currency(currency: str, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    fx_workflow.untrack(db, current_client.id, currency)
    return {"message": "追跡をやめました"}


@router.post("/auto-update")
def auto_update_exchange_rates(db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return fx_workflow.refresh(db, current_client.id)


@router.delete("/{rate_id}")
def delete_exchange_rate(rate_id: int, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    fx_workflow.delete_rate(db, current_client.id, rate_id)
    return {"message": "為替レートを削除しました"}
