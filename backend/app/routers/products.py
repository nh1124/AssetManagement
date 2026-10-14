from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import depreciation_service, product_service
from ..workflows import product_workflow

router = APIRouter(prefix="/products", tags=["products"])


@router.post("/depreciation/run")
def run_depreciation(
    payload: schemas.DepreciationPostRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Write down every product whose next period is this one.

    Declared before the path-parameter routes so "depreciation" is not read as a
    product id. Reports what it skipped rather than failing the batch: one
    product missing an account should not stop the rest.
    """
    return depreciation_service.run_for_period(db, current_client.id, payload.period)


@router.get("/{product_id}/depreciation")
def get_depreciation_schedule(
    product_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return depreciation_service.schedule(db, current_client.id, product_id)


@router.post("/{product_id}/depreciation")
def post_depreciation(
    product_id: int,
    payload: schemas.DepreciationPostRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    transaction, row = depreciation_service.post(
        db, current_client.id, product_id, period=payload.period,
    )
    return {
        "transaction_id": transaction.id,
        "period": row.period,
        "amount_minor": row.amount_minor,
        "schedule": depreciation_service.schedule(db, current_client.id, product_id),
    }


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
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return product_service.enrich_product(product_workflow.create_product(db, current_client.id, product))


@router.put("/{product_id}", response_model=schemas.Product)
def update_product(
    product_id: int,
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    updated = product_workflow.update_product(db, current_client.id, product_id, product)
    if updated is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_service.enrich_product(updated)


@router.patch("/{product_id}", response_model=schemas.Product)
def patch_product(
    product_id: int,
    product: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    updated = product_workflow.patch_product(db, current_client.id, product_id, product)
    if updated is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_service.enrich_product(updated)


@router.delete("/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    if not product_workflow.delete_product(db, current_client.id, product_id):
        raise HTTPException(status_code=404, detail="Product not found")


@router.get("/unit-economics-summary")
def get_unit_economics_summary(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Category breakdown and total monthly cost for consumables."""
    return product_service.get_unit_economics_summary(db, current_client.id)
