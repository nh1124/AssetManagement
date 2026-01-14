from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional
from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/transactions", tags=["transactions"])

@router.get("/", response_model=List[schemas.Transaction])
def get_transactions(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(models.Transaction)
    
    if start_date:
        query = query.filter(models.Transaction.date >= start_date)
    if end_date:
        query = query.filter(models.Transaction.date <= end_date)
    
    return query.order_by(models.Transaction.date.desc()).limit(limit).all()

@router.post("/", response_model=schemas.Transaction)
def create_transaction(transaction: schemas.TransactionCreate, db: Session = Depends(get_db)):
    db_transaction = models.Transaction(**transaction.model_dump())
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction
