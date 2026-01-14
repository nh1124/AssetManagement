from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models
from ..database import get_db
from pydantic import BaseModel

router = APIRouter(prefix="/accounts", tags=["accounts"])

# Pydantic schemas
class AccountCreate(BaseModel):
    name: str
    account_type: str
    balance: float = 0
    budget_limit: Optional[float] = None

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    balance: Optional[float] = None
    budget_limit: Optional[float] = None
    is_active: Optional[bool] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    account_type: str
    balance: float
    budget_limit: Optional[float] = None
    is_active: bool = True

    class Config:
        from_attributes = True

@router.get("/", response_model=List[AccountResponse])
def get_accounts(
    account_type: Optional[str] = Query(None),
    is_active: bool = Query(True),
    db: Session = Depends(get_db)
):
    """Get all accounts, optionally filtered by type."""
    query = db.query(models.Account).filter(models.Account.is_active == is_active)
    
    if account_type:
        query = query.filter(models.Account.account_type == account_type)
    
    return query.order_by(models.Account.account_type, models.Account.name).all()

@router.get("/by-type")
def get_accounts_grouped_by_type(db: Session = Depends(get_db)):
    """Get accounts grouped by type for dropdowns."""
    accounts = db.query(models.Account).filter(models.Account.is_active == True).all()
    
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
                "balance": acc.balance,
                "budget_limit": acc.budget_limit
            })
    
    return grouped

@router.post("/", response_model=AccountResponse)
def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    """Create a new account."""
    db_account = models.Account(**account.model_dump())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account

@router.put("/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, account: AccountUpdate, db: Session = Depends(get_db)):
    """Update an account."""
    db_account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if db_account:
        update_data = account.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_account, key, value)
        db.commit()
        db.refresh(db_account)
    return db_account

@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    """Soft delete an account."""
    db_account = db.query(models.Account).filter(models.Account.id == account_id).first()
    if db_account:
        db_account.is_active = False
        db.commit()
        return {"message": "Account deactivated"}
    return {"message": "Account not found"}

@router.post("/seed-defaults")
def seed_default_accounts(db: Session = Depends(get_db)):
    """Create default accounts if they don't exist."""
    from ..services.accounting_service import ensure_default_accounts
    ensure_default_accounts(db)
    return {"message": "Default accounts seeded"}
