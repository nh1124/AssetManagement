from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
from ..domain.messages import localize, message_of
from ..database import get_db
from ..dependencies import get_current_client, request_language
from .. import models, schemas
from ..services import analysis_service, reconciliation_service
from ..services.ai_policy_service import assert_direct_ledger_write_allowed
from .transactions import _serialize_transaction
from ..services.cache_service import get_or_set
from ..services.reporting_service import (
    get_net_worth_history as reporting_get_net_worth_history,
    get_account_flows_for_range,
    get_account_transactions_for_range,
    get_balance_sheet,
    get_profit_loss,
    get_profit_loss_for_range,
    get_variance_analysis,
    get_variance_analysis_for_range,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.get("/summary")
def get_analysis_summary(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get financial summary for current client."""
    return get_or_set(
        f"client:{current_client.id}:analysis_summary",
        60,
        lambda: analysis_service.get_summary(db, client_id=current_client.id),
    )

@router.get("/balance-sheet")
def get_bs(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Balance Sheet snapshot for current client."""
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
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get Profit & Loss for current client."""
    if start_date and end_date:
        return get_profit_loss_for_range(db, start_date, end_date, client_id=current_client.id)

    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    
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


@router.get("/account-flows")
def get_account_flows(
    start_date: date = Query(...),
    end_date: date = Query(...),
    grain: str = Query(default="month"),
    account_types: Optional[str] = Query(None),
    include_zero: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Get debit/credit movement by account for the Review period flow view."""
    type_filter = [item.strip() for item in account_types.split(",") if item.strip()] if account_types else None
    try:
        return get_account_flows_for_range(
            db,
            start_date,
            end_date,
            grain=grain,
            account_types=type_filter,
            include_zero=include_zero,
            client_id=current_client.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=message_of(exc)) from exc


@router.get("/account-transactions")
def get_account_transactions(
    account_id: int = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Get journal-backed transactions for one account within a Review period."""
    try:
        return get_account_transactions_for_range(
            db,
            account_id,
            start_date,
            end_date,
            limit=limit,
            offset=offset,
            client_id=current_client.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=message_of(exc)) from exc

@router.get("/depreciation")
def get_depreciation(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
    language: str | None = Depends(request_language),
):
    """Get asset depreciation summary for current client."""
    # Each position's blocked_reason is shown on the fixed-asset screen, in its language.
    return localize(analysis_service.get_depreciation_summary(db, client_id=current_client.id), language)

@router.get("/net-position")
def get_net_position(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get net position for current client."""
    return analysis_service.get_net_position(db, client_id=current_client.id)


@router.get("/net-worth-history")
def get_net_worth_history(
    months: int = Query(default=36, ge=1, le=240),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Get month-end net worth history calculated from journal entries."""
    return get_or_set(
        f"client:{current_client.id}:net_worth_history:{months}",
        300,
        lambda: reporting_get_net_worth_history(db, client_id=current_client.id, months=months),
    )


@router.get("/reconcile/{account_id}", response_model=schemas.ReconciliationComparison)
def compare_statement(
    account_id: int,
    as_of: date = Query(...),
    statement: Decimal = Query(..., allow_inf_nan=False),
    currency: str | None = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    money = reconciliation_service.statement_money(db, current_client.id, statement, currency)
    return reconciliation_service.compare_to_statement(
        db, current_client.id, account_id, as_of=as_of,
        statement_minor=money.minor, currency=money.currency,
    )


@router.post("/reconcile/{account_id}/adjust", response_model=schemas.Transaction)
def adjust_statement(
    account_id: int,
    payload: schemas.ReconciliationAdjustment,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
    request: Request = None,
):
    assert_direct_ledger_write_allowed(
        db, current_client.id,
        mcp_client_id=request.headers.get("x-mcp-client-id") if request else None,
        risk="medium",
    )
    money = reconciliation_service.statement_money(db, current_client.id, payload.statement, payload.currency)
    transaction = reconciliation_service.post_adjustment(
        db, current_client.id, account_id, as_of=payload.as_of,
        statement_minor=money.minor, currency=money.currency,
        counter_account_id=payload.counter_account_id,
        capsule_id=payload.capsule_id, note=payload.note,
        expected_ledger_minor=payload.expected_ledger_minor,
    )
    return _serialize_transaction(transaction)
