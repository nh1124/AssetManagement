from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Literal
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
    parent_id: Optional[int] = None
    expected_return: float = 0.0
    role: Literal["defense", "growth", "earmarked", "operating", "unassigned"] = "unassigned"
    role_target_amount: Optional[float] = None

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    balance: Optional[float] = None
    expected_return: Optional[float] = None
    role: Optional[Literal["defense", "growth", "earmarked", "operating", "unassigned"]] = None
    role_target_amount: Optional[float] = None
    is_active: Optional[bool] = None

class AccountResponse(BaseModel):
    id: int
    name: str
    account_type: str
    balance: float
    parent_id: Optional[int] = None
    expected_return: float = 0.0
    role: str = "unassigned"
    role_target_amount: Optional[float] = None
    is_active: bool = True

    class Config:
        from_attributes = True


def _serialize_account(account: models.Account, rollup_balance: float | None = None) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "account_type": account.account_type,
        "balance": account.balance or 0.0,
        "rollup_balance": rollup_balance if rollup_balance is not None else account.balance or 0.0,
        "parent_id": account.parent_id,
        "expected_return": account.expected_return or 0.0,
        "role": account.role or "unassigned",
        "role_target_amount": account.role_target_amount,
        "is_active": account.is_active,
    }


def _validate_parent(
    db: Session,
    client_id: int,
    account_type: str,
    parent_id: int | None,
    account_id: int | None = None,
) -> None:
    if parent_id is None:
        return
    if account_id is not None and parent_id == account_id:
        raise HTTPException(status_code=400, detail="Account cannot be its own parent")

    parent = db.query(models.Account).filter(
        models.Account.id == parent_id,
        models.Account.client_id == client_id,
        models.Account.is_active == True,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent account not found")
    if parent.account_type != account_type:
        raise HTTPException(status_code=400, detail="Parent account must have the same account_type")

    seen = set()
    current = parent
    while current:
        if current.id in seen:
            raise HTTPException(status_code=400, detail="Account hierarchy cycle detected")
        if account_id is not None and current.id == account_id:
            raise HTTPException(status_code=400, detail="Account hierarchy cycle detected")
        seen.add(current.id)
        if current.parent_id is None:
            break
        current = db.query(models.Account).filter(
            models.Account.id == current.parent_id,
            models.Account.client_id == client_id,
        ).first()


def _build_tree(accounts: list[models.Account]) -> dict:
    by_id = {account.id: account for account in accounts}
    children_by_parent: dict[int | None, list[models.Account]] = {}
    for account in accounts:
        parent_id = account.parent_id if account.parent_id in by_id else None
        children_by_parent.setdefault(parent_id, []).append(account)

    def rollup(account: models.Account) -> float:
        return (account.balance or 0.0) + sum(rollup(child) for child in children_by_parent.get(account.id, []))

    def node(account: models.Account) -> dict:
        return {
            **_serialize_account(account, rollup_balance=rollup(account)),
            "children": [node(child) for child in sorted(children_by_parent.get(account.id, []), key=lambda item: item.name)],
        }

    grouped = {"asset": [], "liability": [], "income": [], "expense": []}
    for account in sorted(children_by_parent.get(None, []), key=lambda item: (item.account_type, item.name)):
        if account.account_type in grouped:
            grouped[account.account_type].append(node(account))
    return grouped

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


@router.get("/tree")
def get_account_tree(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    accounts = db.query(models.Account).filter(
        models.Account.client_id == current_client.id,
        models.Account.is_active == True,
    ).all()
    return _build_tree(accounts)

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
                "role": acc.role,
                "role_target_amount": acc.role_target_amount,
            })
    
    return grouped

@router.post("/", response_model=AccountResponse)
def create_account(
    account: AccountCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create a new account for current client."""
    payload = account.model_dump()
    _validate_parent(db, current_client.id, payload["account_type"], payload.get("parent_id"))
    db_account = models.Account(**payload, client_id=current_client.id)
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
    if "parent_id" in update_data:
        next_parent_id = update_data["parent_id"]
        _validate_parent(
            db,
            current_client.id,
            db_account.account_type,
            next_parent_id,
            account_id=db_account.id,
        )
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

    child_count = db.query(models.Account).filter(
        models.Account.parent_id == account_id,
        models.Account.client_id == current_client.id,
        models.Account.is_active == True,
    ).count()
    if child_count:
        raise HTTPException(status_code=400, detail="Account has child accounts")
        
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
