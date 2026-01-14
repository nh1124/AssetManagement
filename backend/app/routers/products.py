from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/products", tags=["products"])

@router.get("/", response_model=List[schemas.Product])
def get_products(
    category: Optional[str] = Query(None),
    is_asset: Optional[bool] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.Product)
    
    if category:
        query = query.filter(models.Product.category == category)
    if is_asset is not None:
        query = query.filter(models.Product.is_asset == is_asset)
    
    return query.all()

@router.post("/", response_model=schemas.Product)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    db_product = models.Product(**product.model_dump())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product
