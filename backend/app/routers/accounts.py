from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Literal
from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services import capsule_service, ledger_service
from ..services.cache_service import invalidate_client
from ..services.ledger_valuation import AccountBalances, calculate_account_balances
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/accounts", tags=["accounts"])

# Pydantic schemas
class AccountEarmarkResponse(BaseModel):
    capsule_id: int
    capsule_name: str
    claimed: float
    claimed_minor: int
    currency: str
    max_share_bp: Optional[int] = None


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    account_type: Literal["asset", "liability", "income", "expense"]
    balance: float = 0
    is_active: bool = True
    liability_closing_day: Optional[int] = None
    liability_payment_day: Optional[int] = None
    liability_payment_month_offset: int = 0
    liability_payment_policy: Literal["full", "minimum", "fixed", "installment", "revolving"] = "full"
    liability_minimum_payment: Optional[float] = None
    liability_fixed_payment_amount: Optional[float] = None
    liability_installment_months: Optional[int] = None
    liability_revolving_rate: Optional[float] = None

class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    balance: Optional[float] = None
    liability_closing_day: Optional[int] = None
    liability_payment_day: Optional[int] = None
    liability_payment_month_offset: Optional[int] = None
    liability_payment_policy: Optional[Literal["full", "minimum", "fixed", "installment", "revolving"]] = None
    liability_minimum_payment: Optional[float] = None
    liability_fixed_payment_amount: Optional[float] = None
    liability_installment_months: Optional[int] = None
    liability_revolving_rate: Optional[float] = None
    is_active: Optional[bool] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    account_type: Literal["asset", "liability", "income", "expense"]
    balance: float
    balances_minor: dict[str, int] = Field(default_factory=dict)
    liability_closing_day: Optional[int] = None
    liability_payment_day: Optional[int] = None
    liability_payment_month_offset: int = 0
    liability_payment_policy: str = "full"
    liability_minimum_payment: Optional[float] = None
    liability_fixed_payment_amount: Optional[float] = None
    liability_installment_months: Optional[int] = None
    liability_revolving_rate: Optional[float] = None
    is_active: bool = True

    class Config:
        from_attributes = True


def _serialize_account(
    account: models.Account,
    balances: AccountBalances,
) -> dict:
    account_balance = balances.balance
    return {
        "id": account.id,
        "name": account.name,
        "account_type": account.account_type,
        "balance": account_balance,
        "balances_minor": balances.balances_minor,
        "liability_closing_day": account.liability_closing_day,
        "liability_payment_day": account.liability_payment_day,
        "liability_payment_month_offset": account.liability_payment_month_offset or 0,
        "liability_payment_policy": account.liability_payment_policy or "full",
        "liability_minimum_payment": account.liability_minimum_payment,
        "liability_fixed_payment_amount": account.liability_fixed_payment_amount,
        "liability_installment_months": account.liability_installment_months,
        "liability_revolving_rate": account.liability_revolving_rate,
        "is_active": account.is_active,
    }


@router.get("/", response_model=List[AccountResponse])
def get_accounts(
    account_type: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all accounts for current client, optionally filtered by type."""
    accounts = ledger_service.list_accounts(
        db, current_client.id, account_type=account_type, is_active=is_active,
    )
    balances = calculate_account_balances(db, accounts)
    return [
        _serialize_account(account, balances=balances[account.id])
        for account in accounts
    ]


@router.get("/{account_id}/earmarks", response_model=List[AccountEarmarkResponse])
def get_account_earmarks(
    account_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if ledger_service.get_account(db, current_client.id, account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return capsule_service.list_account_earmarks(db, current_client.id, account_id)

@router.get("/by-type")
def get_accounts_grouped_by_type(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get accounts for current client grouped by type."""
    accounts = ledger_service.list_accounts(db, current_client.id, ordered=False)
    balances = calculate_account_balances(db, accounts)
    
    grouped = {
        "asset": [],
        "liability": [],
        "income": [],
        "expense": []
    }
    
    for acc in accounts:
        if acc.account_type in grouped:
            grouped[acc.account_type].append({
                "id": acc.id,
                "name": acc.name,
                "balance": balances[acc.id].balance,
                "balances_minor": balances[acc.id].balances_minor,
                "liability_closing_day": acc.liability_closing_day,
                "liability_payment_day": acc.liability_payment_day,
                "liability_payment_month_offset": acc.liability_payment_month_offset or 0,
                "liability_payment_policy": acc.liability_payment_policy or "full",
                "liability_minimum_payment": acc.liability_minimum_payment,
                "liability_fixed_payment_amount": acc.liability_fixed_payment_amount,
                "liability_installment_months": acc.liability_installment_months,
                "liability_revolving_rate": acc.liability_revolving_rate,
            })
    
    return grouped

@router.post("/", response_model=AccountResponse)
def create_account(
    account: AccountCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create a new account for current client."""
    db_account = ledger_service.create_account(db, current_client.id, account.model_dump())
    invalidate_client(current_client.id)
    return _serialize_account(db_account, balances=calculate_account_balances(db, [db_account])[db_account.id])

@router.put("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: int, 
    account: AccountUpdate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Update an account belonging to current client."""
    db_account = ledger_service.update_account(
        db, current_client.id, account_id, account.model_dump(exclude_unset=True),
    )
    if db_account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    invalidate_client(current_client.id)
    return _serialize_account(db_account, balances=calculate_account_balances(db, [db_account])[db_account.id])

@router.delete("/{account_id}")
def delete_account(
    account_id: int, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Soft delete an account belonging to current client."""
    if not ledger_service.delete_account(db, current_client.id, account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    invalidate_client(current_client.id)
    return {"message": "Account deactivated"}

@router.post("/seed-defaults")
def seed_default_accounts(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create default accounts for current client."""
    from ..services.ledger_service import ensure_default_accounts
    # We need to update ensure_default_accounts to accept client_id
    ensure_default_accounts(db, client_id=current_client.id)
    invalidate_client(current_client.id)
    return {"message": "Default accounts seeded"}
