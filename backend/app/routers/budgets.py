from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client

router = APIRouter(prefix="/budgets", tags=["budgets"])

@router.get("/", response_model=List[schemas.Budget])
def get_budgets(
    month: Optional[str] = Query(None), 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    query = db.query(models.Budget).filter(models.Budget.client_id == current_client.id)
    if month:
        query = query.filter(models.Budget.month == month)
    return query.all()

@router.post("/", response_model=schemas.Budget)
def create_budget(
    budget: schemas.BudgetCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    db_budget = models.Budget(**budget.model_dump(), client_id=current_client.id)
    db.add(db_budget)
    db.commit()
    db.refresh(db_budget)
    return db_budget

