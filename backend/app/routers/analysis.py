from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
from ..database import get_db
from ..dependencies import get_current_client
from .. import models
from ..services import analysis_service
from ..services.accounting_service import (
    ensure_default_accounts,
    get_balance_sheet,
    get_profit_loss,
    get_profit_loss_for_range,
    get_profit_loss_rollup,
    get_profit_loss_rollup_for_range,
    get_variance_analysis,
    get_variance_analysis_for_range,
)
from ..services.reconcile_service import run_reconcile

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
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Balance Sheet snapshot for current client."""
    ensure_default_accounts(db, client_id=current_client.id)
    if as_of is None:
        if year and month:
            # Get B/S as of end of month.
            if month == 12:
                as_of = date(year, 12, 31)
            else:
                as_of = date(year, month + 1, 1) - date.resolution
        else:
            as_of = date.today()
    
    return get_balance_sheet(db, as_of, client_id=current_client.id)

@router.get("/profit-loss")
def get_pl(
    year: int = Query(default=None),
    month: int = Query(default=None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    rollup: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Profit & Loss for current client."""
    ensure_default_accounts(db, client_id=current_client.id)
    if start_date and end_date:
        if rollup:
            return get_profit_loss_rollup_for_range(db, start_date, end_date, client_id=current_client.id)
        return get_profit_loss_for_range(db, start_date, end_date, client_id=current_client.id)

    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    
    if rollup:
        return get_profit_loss_rollup(db, year, month, client_id=current_client.id)
    return get_profit_loss(db, year, month, client_id=current_client.id)

@router.get("/variance")
def get_variance(
    year: int = Query(default=None),
    month: int = Query(default=None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Budget vs Actual variance analysis for current client."""
    if start_date and end_date:
        return get_variance_analysis_for_range(db, start_date, end_date, client_id=current_client.id)

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


@router.get("/net-worth-history")
def get_net_worth_history(
    months: int = Query(default=36, ge=1, le=240),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Get month-end net worth history calculated from journal entries."""
    return analysis_service.get_net_worth_history(db, client_id=current_client.id, months=months)


@router.get("/reconcile")
def check_reconcile(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Check discrepancies between journal-based and stored account balances."""
    discrepancies = run_reconcile(db, client_id=current_client.id, fix=False)
    return {
        "status": "ok" if not discrepancies else "discrepancies_found",
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies,
    }


@router.post("/reconcile/fix")
def fix_reconcile(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Fix account balances using journal-entry truth values."""
    fixed = run_reconcile(db, client_id=current_client.id, fix=True)
    return {
        "status": "fixed",
        "fixed_count": len(fixed),
        "fixed_accounts": fixed,
    }

