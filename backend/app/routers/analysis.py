from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
from ..database import get_db
from ..services import analysis_service
from ..services.accounting_service import get_balance_sheet, get_profit_loss, get_variance_analysis, ensure_default_accounts

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.get("/summary")
def get_analysis_summary(db: Session = Depends(get_db)):
    """Get financial summary with CFO logic."""
    ensure_default_accounts(db)
    return analysis_service.get_summary(db)

@router.get("/balance-sheet")
def get_bs(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Get Balance Sheet snapshot."""
    ensure_default_accounts(db)
    if year and month:
        # Get B/S as of end of month
        if month == 12:
            as_of = date(year + 1, 1, 1)
        else:
            as_of = date(year, month + 1, 1)
    else:
        as_of = date.today()
    
    return get_balance_sheet(db, as_of)

@router.get("/profit-loss")
def get_pl(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db)
):
    """Get Profit & Loss for a specific month."""
    ensure_default_accounts(db)
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    
    return get_profit_loss(db, year, month)

@router.get("/variance")
def get_variance(
    year: int = Query(default=None),
    month: int = Query(default=None),
    db: Session = Depends(get_db)
):
    """Get Budget vs Actual variance analysis."""
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    
    return get_variance_analysis(db, year, month)

@router.get("/depreciation")
def get_depreciation(db: Session = Depends(get_db)):
    """Get asset depreciation summary."""
    return analysis_service.get_depreciation_summary(db)

@router.get("/net-position")
def get_net_position(db: Session = Depends(get_db)):
    """Get net position including future life event costs."""
    ensure_default_accounts(db)
    return analysis_service.get_net_position(db)
