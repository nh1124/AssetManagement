from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import product_service
from ..workflows import product_workflow

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/", response_model=List[schemas.Product])
def get_products(
    category: Optional[str] = Query(None),
    is_asset: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    products = product_service.list_products(db, current_client.id, category=category, is_asset=is_asset)
    return [product_service.enrich_product(product) for product in products]


@router.post("/", response_model=schemas.Product)
def create_product(
    product: schemas.ProductCreate,
    reserve_fingerprint: Optional[str] = Query(None, max_length=64),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return product_service.enrich_product(product_workflow.create_product(
        db, current_client.id, product, reserve_fingerprint=reserve_fingerprint,
    ))


@router.put("/{product_id}", response_model=schemas.Product)
def update_product(
    product_id: int,
    product: schemas.ProductCreate,
    reserve_fingerprint: Optional[str] = Query(None, max_length=64),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    updated = product_workflow.update_product(
        db, current_client.id, product_id, product, reserve_fingerprint=reserve_fingerprint,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_service.enrich_product(updated)


@router.patch("/{product_id}", response_model=schemas.Product)
def patch_product(
    product_id: int,
    product: schemas.ProductUpdate,
    reserve_fingerprint: Optional[str] = Query(None, max_length=64),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    updated = product_workflow.patch_product(
        db, current_client.id, product_id, product, reserve_fingerprint=reserve_fingerprint,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_service.enrich_product(updated)


@router.delete("/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    reserve_fingerprint: Optional[str] = Query(None, max_length=64),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not product_workflow.delete_product(
        db, current_client.id, product_id, reserve_fingerprint=reserve_fingerprint,
    ):
        raise HTTPException(status_code=404, detail="Product not found")


@router.get("/unit-economics-summary")
def get_unit_economics_summary(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Category breakdown and total monthly cost for consumables."""
    return product_service.get_unit_economics_summary(db, current_client.id)
