from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client

router = APIRouter(prefix="/products", tags=["products"])


def enrich_product(product: models.Product) -> dict:
    """Return product with unit economics fields."""
    units = product.units_per_purchase or 1
    unit_cost = product.last_unit_price / units

    if not product.is_asset and product.frequency_days and product.frequency_days > 0:
        monthly_cost = unit_cost * (30 / product.frequency_days)
    else:
        monthly_cost = 0.0

    next_purchase_date = None
    if product.last_purchase_date and product.frequency_days:
        next_purchase_date = (
            product.last_purchase_date + timedelta(days=product.frequency_days)
        ).isoformat()

    return {
        "id": product.id,
        "name": product.name,
        "category": product.category,
        "location": product.location,
        "last_unit_price": product.last_unit_price,
        "units_per_purchase": units,
        "unit_cost": round(unit_cost, 2),
        "frequency_days": product.frequency_days,
        "last_purchase_date": product.last_purchase_date,
        "is_asset": product.is_asset,
        "lifespan_months": product.lifespan_months,
        "purchase_price": product.purchase_price,
        "purchase_date": product.purchase_date,
        "monthly_cost": round(monthly_cost, 2),
        "next_purchase_date": next_purchase_date,
    }


@router.get("/", response_model=List[schemas.Product])
def get_products(
    category: Optional[str] = Query(None),
    is_asset: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    query = db.query(models.Product).filter(models.Product.client_id == current_client.id)

    if category:
        query = query.filter(models.Product.category == category)
    if is_asset is not None:
        query = query.filter(models.Product.is_asset == is_asset)

    products = query.all()
    return [enrich_product(p) for p in products]


@router.post("/", response_model=schemas.Product)
def create_product(
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    db_product = models.Product(**product.model_dump(), client_id=current_client.id)
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return enrich_product(db_product)


@router.put("/{product_id}", response_model=schemas.Product)
def update_product(
    product_id: int,
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    db_product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.client_id == current_client.id,
    ).first()

    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")

    for key, value in product.model_dump().items():
        setattr(db_product, key, value)
    db.commit()
    db.refresh(db_product)
    return enrich_product(db_product)


@router.delete("/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    db_product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.client_id == current_client.id,
    ).first()

    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")

    db.delete(db_product)
    db.commit()


@router.get("/unit-economics-summary")
def get_unit_economics_summary(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Category breakdown and total monthly cost for consumables."""
    consumables = db.query(models.Product).filter(
        models.Product.client_id == current_client.id,
        models.Product.is_asset.is_(False),
        models.Product.frequency_days > 0,
    ).all()

    items = []
    total_monthly_cost = 0.0

    for product in consumables:
        units = product.units_per_purchase or 1
        unit_cost = product.last_unit_price / units
        monthly_cost = unit_cost * (30 / product.frequency_days)
        total_monthly_cost += monthly_cost
        items.append(
            {
                "name": product.name,
                "category": product.category,
                "unit_cost": round(unit_cost, 2),
                "monthly_cost": round(monthly_cost, 2),
            }
        )

    items.sort(key=lambda x: x["monthly_cost"], reverse=True)

    category_totals: dict[str, float] = {}
    for item in items:
        category = item["category"]
        category_totals[category] = category_totals.get(category, 0.0) + item["monthly_cost"]

    return {
        "items": items,
        "category_breakdown": [
            {"category": k, "monthly_cost": round(v, 2)}
            for k, v in sorted(category_totals.items(), key=lambda x: -x[1])
        ],
        "total_monthly_cost": round(total_monthly_cost, 2),
    }
