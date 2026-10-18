from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import Conflict, Invalid
from ..services import capsule_service, ledger_service, product_service
from ..services.cache_service import invalidate_client
from ..services.product_reserve_service import (
    capsule_amounts, ensure_default_product_reserve_pools, refresh_product_capsules,
)
from ..services.registry_service import detach_product, get_product_entry


def validate_budget_account(db: Session, client_id: int, budget_account_id: int | None) -> None:
    if budget_account_id is None:
        return
    account = ledger_service.get_expense_account(db, client_id, budget_account_id)
    if not account:
        raise Invalid("Budget account must be an expense account for this client")


def validate_funding_capsule(db: Session, client_id: int, funding_capsule_id: int | None) -> None:
    if funding_capsule_id is None:
        return
    capsule = capsule_service.get_product_funding_capsule(db, client_id, funding_capsule_id)
    if not capsule:
        raise Invalid("Funding capsule must be a non-LifeEvent capsule for this client")


def default_funding_capsule_id(db: Session, client_id: int, is_asset: bool) -> int:
    pools = ensure_default_product_reserve_pools(db, client_id)
    target_name = "Fixed Asset Reserve" if is_asset else "Item Reserve"
    return next(pool.id for pool in pools if pool.name == target_name)


def normalize_product_data(db: Session, client_id: int, data: dict) -> dict:
    validate_budget_account(db, client_id, data.get("budget_account_id"))
    validate_funding_capsule(db, client_id, data.get("funding_capsule_id"))

    if data.get("budget_account_id"):
        account = ledger_service.get_account(db, client_id, data["budget_account_id"])
        if account:
            data["category"] = account.name
    else:
        data["category"] = data.get("category") or "Uncategorized"

    if product_service.product_uses_reserve(data):
        if data.get("funding_capsule_id") is None:
            data["funding_capsule_id"] = default_funding_capsule_id(db, client_id, data.get("is_asset", False))
    else:
        data["funding_capsule_id"] = None
    return data


def confirm_reserve_changes(db: Session, client_id: int, before: dict[int, dict], fingerprint: str | None) -> None:
    """Refuse a save that moves an earmark's target or monthly amount unless it was confirmed.

    The refusal is the preview: it lists the changes and their fingerprint, and the same
    save repeated with that fingerprint confirms exactly those changes. Anything that moved
    in between (another product, or a fixed asset's month passing) changes the fingerprint
    and is refused again, so no path rewrites an earmark unseen.
    """
    after = capsule_amounts(db, client_id, before)
    moved = [capsule_id for capsule_id, row in sorted(after.items())
             if (row["target_minor"], row["monthly_minor"])
             != (before[capsule_id]["target_minor"], before[capsule_id]["monthly_minor"])]
    if not moved:
        return
    expected = hashlib.sha256(json.dumps([[
        capsule_id, before[capsule_id]["target_minor"], after[capsule_id]["target_minor"],
        before[capsule_id]["monthly_minor"], after[capsule_id]["monthly_minor"],
    ] for capsule_id in moved]).encode()).hexdigest()
    if fingerprint == expected:
        return
    raise Conflict("Saving this product changes earmark amounts; confirm them first", payload={
        "code": "reserve_changes_unconfirmed",
        "message": "Saving this product changes earmark amounts. Repeat the save with reserve_fingerprint to confirm.",
        "fingerprint": expected,
        "changes": [{
            "capsule_id": capsule_id, "name": after[capsule_id]["name"],
            "target_before": before[capsule_id]["target"], "target_after": after[capsule_id]["target"],
            "monthly_before": before[capsule_id]["monthly"], "monthly_after": after[capsule_id]["monthly"],
        } for capsule_id in moved],
    })


def create_product(
    db: Session, client_id: int, payload: schemas.ProductCreate, *,
    reserve_fingerprint: str | None = None, commit: bool = True,
) -> models.Product:
    data = normalize_product_data(db, client_id, payload.model_dump())
    before = capsule_amounts(db, client_id, [data["funding_capsule_id"]])
    product = product_service.create_product(db, client_id, data, commit=False)
    refresh_product_capsules(db, client_id, [product.funding_capsule_id])
    confirm_reserve_changes(db, client_id, before, reserve_fingerprint)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    return product


def update_product(
    db: Session, client_id: int, product_id: int, payload: schemas.ProductCreate,
    *, reserve_fingerprint: str | None = None, commit: bool = True,
) -> models.Product | None:
    product = product_service.get_product(db, client_id, product_id)
    if product is None:
        return None
    previous_capsule_id = product.funding_capsule_id
    data = normalize_product_data(db, client_id, payload.model_dump())
    before = capsule_amounts(db, client_id, [previous_capsule_id, data["funding_capsule_id"]])
    product = product_service.update_product(db, client_id, product_id, data, commit=False)
    refresh_product_capsules(db, client_id, [previous_capsule_id, product.funding_capsule_id])
    confirm_reserve_changes(db, client_id, before, reserve_fingerprint)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    return product


def patch_product(
    db: Session, client_id: int, product_id: int, patch: schemas.ProductUpdate,
    *, reserve_fingerprint: str | None = None, commit: bool = True,
) -> models.Product | None:
    product = product_service.get_product(db, client_id, product_id)
    if product is None:
        return None
    previous_capsule_id = product.funding_capsule_id
    data = patch.model_dump(exclude_unset=True)
    merged = {
        column.name: getattr(product, column.name)
        for column in models.Product.__table__.columns
        if column.name not in {"id", "client_id", "created_at"}
    }
    merged.update(data)
    merged = normalize_product_data(db, client_id, merged)
    changes = {key: merged.get(key) for key in data}
    if "budget_account_id" in data and "category" not in data:
        changes["category"] = merged.get("category")
    if "funding_capsule_id" in data or "budget_treatment" in data or "is_asset" in data:
        changes["funding_capsule_id"] = merged.get("funding_capsule_id")
    before = capsule_amounts(db, client_id, [previous_capsule_id, merged.get("funding_capsule_id")])
    product = product_service.update_product(db, client_id, product_id, changes, commit=False)
    refresh_product_capsules(db, client_id, [previous_capsule_id, product.funding_capsule_id])
    confirm_reserve_changes(db, client_id, before, reserve_fingerprint)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    return product


def delete_product(
    db: Session, client_id: int, product_id: int, *,
    reserve_fingerprint: str | None = None, commit: bool = True,
) -> bool:
    product = product_service.get_product(db, client_id, product_id)
    if product is None:
        return False
    capsule_id = product.funding_capsule_id
    before = capsule_amounts(db, client_id, [capsule_id])
    registry = get_product_entry(db, client_id, product.id)
    if registry:
        detach_product(db, registry)
    product_service.delete_product(db, client_id, product_id, commit=False)
    refresh_product_capsules(db, client_id, [capsule_id])
    confirm_reserve_changes(db, client_id, before, reserve_fingerprint)
    if commit:
        db.commit()
        invalidate_client(client_id)
    return True
