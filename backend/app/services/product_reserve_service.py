from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models


DEFAULT_PRODUCT_RESERVE_POOLS = (
    ("Fixed Asset Reserve", True),
    ("Item Reserve", False),
)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, 28)
    return date(year, month, day)


def _months_until(target: date, reference_date: date) -> int:
    months = (target.year - reference_date.year) * 12 + (target.month - reference_date.month)
    if target.day > reference_date.day:
        months += 1
    return max(1, months)


def product_reserve_values(product: models.Product, reference_date: date | None = None) -> dict:
    reference_date = reference_date or date.today()
    if product.is_asset:
        target_amount = float(product.purchase_price or product.last_unit_price or 0.0)
        if product.purchase_date and product.lifespan_months:
            replacement_date = _add_months(product.purchase_date, product.lifespan_months)
            months = _months_until(replacement_date, reference_date)
        else:
            months = max(1, int(product.lifespan_months or 0))
        monthly = target_amount / months if target_amount > 0 and months > 0 else 0.0
        return {
            "reserve_target_amount": round(target_amount, 0),
            "recommended_monthly_reserve": round(monthly, 0),
        }

    units = product.units_per_purchase or 1
    unit_cost = (product.last_unit_price or 0.0) / units if units else (product.last_unit_price or 0.0)
    monthly = unit_cost * (30 / product.frequency_days) if product.frequency_days and product.frequency_days > 0 else 0.0
    return {
        "reserve_target_amount": round(product.last_unit_price or 0.0, 0),
        "recommended_monthly_reserve": round(monthly, 0),
    }


def ensure_default_product_reserve_pools(db: Session, client_id: int) -> list[models.Capsule]:
    pools: list[models.Capsule] = []
    for name, _is_asset in DEFAULT_PRODUCT_RESERVE_POOLS:
        capsule = db.query(models.Capsule).filter(
            models.Capsule.client_id == client_id,
            models.Capsule.name == name,
        ).first()
        if not capsule:
            capsule = models.Capsule(
                client_id=client_id,
                name=name,
                target_amount=0.0,
                monthly_contribution=0.0,
                current_balance=0.0,
                capsule_type="product_pool",
                target_amount_source="linked_products",
                monthly_contribution_source="linked_products",
            )
            db.add(capsule)
            db.flush()
        else:
            capsule.capsule_type = capsule.capsule_type or "product_pool"
            if capsule.capsule_type == "manual":
                capsule.capsule_type = "product_pool"
        pools.append(capsule)
    return pools


def sync_product_reserve_capsules(db: Session, client_id: int) -> dict:
    products = db.query(models.Product).filter(
        models.Product.client_id == client_id,
        models.Product.funding_capsule_id.isnot(None),
    ).all()
    capsule_ids = {product.funding_capsule_id for product in products if product.funding_capsule_id}
    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id,
        models.Capsule.id.in_(capsule_ids or {-1}),
    ).all()
    capsule_by_id = {capsule.id: capsule for capsule in capsules}
    totals = {
        capsule_id: {"target_amount": 0.0, "monthly_contribution": 0.0, "products": 0}
        for capsule_id in capsule_by_id
    }
    for product in products:
        capsule = capsule_by_id.get(product.funding_capsule_id)
        if not capsule:
            continue
        values = product_reserve_values(product)
        totals[capsule.id]["target_amount"] += values["reserve_target_amount"]
        totals[capsule.id]["monthly_contribution"] += values["recommended_monthly_reserve"]
        totals[capsule.id]["products"] += 1

    updated = []
    for capsule_id, values in totals.items():
        capsule = capsule_by_id[capsule_id]
        capsule.capsule_type = "product_pool"
        capsule.target_amount_source = "linked_products"
        capsule.monthly_contribution_source = "linked_products"
        capsule.target_amount = round(values["target_amount"], 0)
        capsule.monthly_contribution = round(values["monthly_contribution"], 0)
        updated.append({
            "capsule_id": capsule.id,
            "capsule_name": capsule.name,
            "products": values["products"],
            "target_amount": capsule.target_amount,
            "monthly_contribution": capsule.monthly_contribution,
        })
    return {
        "updated_capsules": len(updated),
        "total_monthly_contribution": round(sum(item["monthly_contribution"] for item in updated), 0),
        "capsules": updated,
    }
