from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy.orm import Session

from .money_storage import to_minor, money_client_currency

from .. import models


DEFAULT_PRODUCT_RESERVE_POOLS = (
    ("Fixed Asset Reserve", True),
    ("Item Reserve", False),
)

RESERVE_TREATMENTS = {"reserve_allocation", "asset_replacement"}


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
    if effective_budget_treatment(product) not in RESERVE_TREATMENTS:
        return {
            "reserve_target_amount": 0.0,
            "recommended_monthly_reserve": 0.0,
        }

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


def effective_budget_treatment(product: models.Product) -> str:
    treatment = product.budget_treatment or "auto"
    if treatment != "auto":
        return treatment
    if product.is_asset:
        return "asset_replacement"
    if product.frequency_days and product.frequency_days <= 45:
        return "expense_only"
    return "reserve_allocation"


def should_use_reserve(product: models.Product) -> bool:
    return effective_budget_treatment(product) in RESERVE_TREATMENTS


def refresh_product_capsules(
    db: Session, client_id: int, capsule_ids: Iterable[int | None],
) -> list[dict]:
    db.flush()
    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id,
        models.Capsule.id.in_({capsule_id for capsule_id in capsule_ids if capsule_id is not None}),
    ).all()
    refreshed = []
    for capsule in capsules:
        products = [product for product in db.query(models.Product).filter(
            models.Product.client_id == client_id,
            models.Product.funding_capsule_id == capsule.id,
        ).all() if should_use_reserve(product)]
        if products:
            reserves = [product_reserve_values(product) for product in products]
            currency = money_client_currency(db, client_id)
            capsule.capsule_type = "product_pool"
            capsule.target_amount_source = capsule.monthly_contribution_source = "linked_products"
            capsule.target_amount_minor = to_minor(sum(value["reserve_target_amount"] for value in reserves), currency)
            capsule.monthly_contribution_minor = to_minor(sum(value["recommended_monthly_reserve"] for value in reserves), currency)
        elif "linked_products" in {capsule.target_amount_source, capsule.monthly_contribution_source}:
            # Keep the last amounts available for the user to manage manually.
            capsule.target_amount_source = capsule.monthly_contribution_source = "manual"
        refreshed.append({
            "capsule_id": capsule.id,
            "products": len(products),
            "target_amount": float(capsule.target_amount or 0.0),
            "monthly_contribution": float(capsule.monthly_contribution or 0.0),
        })
    db.flush()
    return refreshed


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
                target_amount_minor=to_minor(0.0, money_client_currency(db, client_id)),
                monthly_contribution_minor=to_minor(0.0, money_client_currency(db, client_id)),
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




def reserve_totals_by_capsule(db: Session, client_id: int, reference_date: date | None = None) -> dict[int, dict]:
    """Monthly reserve each capsule's products need now: {capsule_id: {monthly, target, products}}.

    Read live rather than from the capsule, because a fixed asset's monthly amount
    grows as its replacement date nears.
    """
    totals: dict[int, dict] = {}
    for product in db.query(models.Product).filter(
        models.Product.client_id == client_id, models.Product.funding_capsule_id.isnot(None),
    ).all():
        if not should_use_reserve(product):
            continue
        values = product_reserve_values(product, reference_date)
        row = totals.setdefault(product.funding_capsule_id, {"monthly": 0.0, "target": 0.0, "products": 0})
        row["monthly"] += values["recommended_monthly_reserve"]
        row["target"] += values["reserve_target_amount"]
        row["products"] += 1
    return totals
