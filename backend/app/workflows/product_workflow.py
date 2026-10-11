from __future__ import annotations

from sqlalchemy.orm import Session
from fastapi import HTTPException

from .. import models, schemas
from ..services import product_service
from ..services.cache_service import invalidate_client
from ..services.product_reserve_service import ensure_default_product_reserve_pools
from ..services.registry_service import detach_product


def validate_budget_account(db: Session, client_id: int, budget_account_id: int | None) -> None:
    if budget_account_id is None:
        return
    account = db.query(models.Account).filter(
        models.Account.id == budget_account_id,
        models.Account.client_id == client_id,
        models.Account.account_type == "expense",
    ).first()
    if not account:
        raise HTTPException(status_code=400, detail="Budget account must be an expense account for this client")


def validate_funding_capsule(db: Session, client_id: int, funding_capsule_id: int | None) -> None:
    if funding_capsule_id is None:
        return
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == funding_capsule_id,
        models.Capsule.client_id == client_id,
        models.Capsule.life_event_id.is_(None),
    ).first()
    if not capsule:
        raise HTTPException(status_code=400, detail="Funding capsule must be a non-LifeEvent capsule for this client")


def default_funding_capsule_id(db: Session, client_id: int, is_asset: bool) -> int:
    pools = ensure_default_product_reserve_pools(db, client_id)
    target_name = "Fixed Asset Reserve" if is_asset else "Item Reserve"
    return next(pool.id for pool in pools if pool.name == target_name)


def normalize_product_data(db: Session, client_id: int, data: dict) -> dict:
    validate_budget_account(db, client_id, data.get("budget_account_id"))
    validate_funding_capsule(db, client_id, data.get("funding_capsule_id"))

    if data.get("budget_account_id"):
        account = db.query(models.Account).filter(
            models.Account.id == data["budget_account_id"],
            models.Account.client_id == client_id,
        ).first()
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


def create_product(
    db: Session, client_id: int, payload: schemas.ProductCreate, *, commit: bool = True,
) -> models.Product:
    data = normalize_product_data(db, client_id, payload.model_dump())
    product = product_service.create_product(db, client_id, data, commit=False)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    return product


def update_product(
    db: Session, client_id: int, product_id: int, payload: schemas.ProductCreate,
    *, commit: bool = True,
) -> models.Product | None:
    if product_service.get_product(db, client_id, product_id) is None:
        return None
    data = normalize_product_data(db, client_id, payload.model_dump())
    product = product_service.update_product(db, client_id, product_id, data, commit=False)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    return product


def patch_product(
    db: Session, client_id: int, product_id: int, patch: schemas.ProductUpdate,
    *, commit: bool = True,
) -> models.Product | None:
    product = product_service.get_product(db, client_id, product_id)
    if product is None:
        return None
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
    product = product_service.update_product(db, client_id, product_id, changes, commit=False)
    if commit:
        db.commit()
        db.refresh(product)
        invalidate_client(client_id)
    return product


def delete_product(
    db: Session, client_id: int, product_id: int, *, commit: bool = True,
) -> bool:
    product = product_service.get_product(db, client_id, product_id)
    if product is None:
        return False
    registry = db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == client_id,
        models.RegistryEntry.source_product_id == product.id,
    ).first()
    if registry:
        detach_product(db, registry)
    product_service.delete_product(db, client_id, product_id, commit=False)
    if commit:
        db.commit()
        invalidate_client(client_id)
    return True
