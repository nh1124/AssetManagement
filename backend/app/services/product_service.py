from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from .money_storage import minor_fields, money_client_currency

from .. import models
from .cache_service import invalidate_client
from .product_reserve_service import effective_budget_treatment, product_reserve_values, should_use_reserve


def get_product(db: Session, client_id: int, product_id: int) -> models.Product | None:
    return db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.client_id == client_id,
    ).first()


def list_products(
    db: Session, client_id: int, *, category: str | None = None, is_asset: bool | None = None,
) -> list[models.Product]:
    query = db.query(models.Product).filter(models.Product.client_id == client_id)
    if category:
        query = query.filter(models.Product.category == category)
    if is_asset is not None:
        query = query.filter(models.Product.is_asset == is_asset)
    return query.all()


def product_uses_reserve(data: dict) -> bool:
    probe = models.Product(**{key: value for key, value in data.items()
                             if key not in {"last_unit_price", "purchase_price"} and hasattr(models.Product, key)})
    return should_use_reserve(probe)


def create_product(
    db: Session, client_id: int, data: dict, *, commit: bool = True,
) -> models.Product:
    product = models.Product(**minor_fields(data, money_client_currency(db, client_id), 'last_unit_price', 'purchase_price'), client_id=client_id)
    db.add(product)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    else:
        db.flush()
    return product


def update_product(
    db: Session, client_id: int, product_id: int, data: dict, *, commit: bool = True,
) -> models.Product | None:
    product = get_product(db, client_id, product_id)
    if product is None:
        return None
    for key, value in minor_fields(data, money_client_currency(db, client_id), "last_unit_price", "purchase_price").items():
        setattr(product, key, value)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    else:
        db.flush()
    return product


def delete_product(
    db: Session, client_id: int, product_id: int, *, commit: bool = True,
) -> bool:
    product = get_product(db, client_id, product_id)
    if product is None:
        return False
    db.delete(product)
    if commit:
        db.commit()
        invalidate_client(client_id)
    else:
        db.flush()
    return True


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

    reserve_values = product_reserve_values(product)
    effective_treatment = effective_budget_treatment(product)
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
        "budget_account_id": product.budget_account_id,
        "budget_account_name": product.budget_account.name if product.budget_account else None,
        "funding_capsule_id": product.funding_capsule_id,
        "funding_capsule_name": product.funding_capsule.name if product.funding_capsule else None,
        "budget_treatment": product.budget_treatment or "auto",
        "effective_budget_treatment": effective_treatment,
        **reserve_values,
        "purchase_price": product.purchase_price,
        "purchase_date": product.purchase_date,
        # The response is built field by field, so a column added to the model is
        # invisible to every caller until it is named here.
        "auto_depreciation": product.auto_depreciation,
        "depreciation_method": product.depreciation_method or "none",
        "depreciation_annual_rate": product.depreciation_annual_rate,
        "depreciation_interval": product.depreciation_interval or "monthly",
        "depreciation_start_date": product.depreciation_start_date,
        "depreciation_expense_account_id": product.depreciation_expense_account_id,
        "depreciation_asset_account_id": product.depreciation_asset_account_id,
        "monthly_cost": round(monthly_cost, 2),
        "next_purchase_date": next_purchase_date,
    }


def get_unit_economics_summary(db: Session, client_id: int) -> dict:
    consumables = db.query(models.Product).filter(
        models.Product.client_id == client_id,
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
                "category": product.budget_account.name if product.budget_account else product.category,
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
