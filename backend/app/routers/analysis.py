from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
from ..database import get_db
from ..dependencies import get_current_client
from .. import models
from ..services import analysis_service
from ..services.accounting_service import get_balance_sheet, get_profit_loss, get_variance_analysis, ensure_default_accounts

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.get("/summary")
def get_analysis_summary(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get financial summary for current client."""
    ensure_default_accounts(db, client_id=current_client.id)
    return analysis_service.get_summary(db, client_id=current_client.id)

@router.get("/balance-sheet")
def get_bs(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Balance Sheet snapshot for current client."""
    ensure_default_accounts(db, client_id=current_client.id)
    if year and month:
        # Get B/S as of end of month
        if month == 12:
            as_of = date(year + 1, 1, 1)
        else:
            as_of = date(year, month + 1, 1)
    else:
        as_of = date.today()
    
    return get_balance_sheet(db, as_of, client_id=current_client.id)

@router.get("/profit-loss")
def get_pl(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Profit & Loss for current client."""
    ensure_default_accounts(db, client_id=current_client.id)
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    
    return get_profit_loss(db, year, month, client_id=current_client.id)

@router.get("/variance")
def get_variance(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Budget vs Actual variance analysis for current client."""
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    
    return get_variance_analysis(db, year, month, client_id=current_client.id)

@router.get("/depreciation")
def get_depreciation(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get asset depreciation summary for current client."""
    return analysis_service.get_depreciation_summary(db, client_id=current_client.id)

@router.get("/net-position")
def get_net_position(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get net position for current client."""
    ensure_default_accounts(db, client_id=current_client.id)
    return analysis_service.get_net_position(db, client_id=current_client.id)

