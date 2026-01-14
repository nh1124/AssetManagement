from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models
from ..database import get_db
from ..dependencies import get_current_client
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
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all accounts for current client, optionally filtered by type."""
    query = db.query(models.Account).filter(
        models.Account.client_id == current_client.id,
        models.Account.is_active == is_active
    )
    
    if account_type:
        query = query.filter(models.Account.account_type == account_type)
    
    return query.order_by(models.Account.account_type, models.Account.name).all()

@router.get("/by-type")
def get_accounts_grouped_by_type(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get accounts for current client grouped by type."""
    accounts = db.query(models.Account).filter(
        models.Account.client_id == current_client.id,
        models.Account.is_active == True
    ).all()
    
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
def create_account(
    account: AccountCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create a new account for current client."""
    db_account = models.Account(**account.model_dump(), client_id=current_client.id)
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account

@router.put("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: int, 
    account: AccountUpdate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Update an account belonging to current client."""
    db_account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == current_client.id
    ).first()
    
    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")
        
    update_data = account.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_account, key, value)
    db.commit()
    db.refresh(db_account)
    return db_account

@router.delete("/{account_id}")
def delete_account(
    account_id: int, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Soft delete an account belonging to current client."""
    db_account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == current_client.id
    ).first()
    
    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")
        
    db_account.is_active = False
    db.commit()
    return {"message": "Account deactivated"}

@router.post("/seed-defaults")
def seed_default_accounts(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create default accounts for current client."""
    from ..services.accounting_service import ensure_default_accounts
    # We need to update ensure_default_accounts to accept client_id
    ensure_default_accounts(db, client_id=current_client.id)
    return {"message": "Default accounts seeded"}
