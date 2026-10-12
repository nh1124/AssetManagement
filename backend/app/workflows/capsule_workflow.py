from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid, NotFound
from ..domain.journal import Leg
from ..domain.money import Money
from ..services import capsule_service, ledger_service
from ..services.cache_service import invalidate_client
from ..services.goal_service import get_life_event
from ..services.fx_service import get_client_currency
from ..services.product_reserve_service import (
    ensure_default_product_reserve_pools,
    sync_product_reserve_capsules,
)


def contribute(
    db: Session, client_id: int, capsule_id: int, *, amount: float,
    from_account_id: int, commit: bool = True,
) -> dict:
    capsule = capsule_service.get_capsule(db, client_id, capsule_id)
    if not capsule:
        raise NotFound("Capsule not found")
    from_account = ledger_service.get_account(db, client_id, from_account_id)
    if not from_account:
        raise NotFound("Source account not found")
    if amount <= 0:
        raise Invalid("Contribution amount must be positive")

    sources = capsule_service.list_funding_sources(db, client_id, capsule.id)
    if not sources:
        raise NotFound("Reservation account not found")
    for source in sources:
        if not ledger_service.get_account(db, client_id, source.account_id):
            raise NotFound("Reservation account not found")
    remaining = capsule_service.remaining_target(db, capsule)
    if remaining <= 0:
        return {
            "status": "skipped",
            "message": "Capsule target already reached",
            "amount": 0.0,
            "new_balance": capsule_service.capsule_balance(db, capsule),
        }
    amount = min(amount, remaining)
    currency = get_client_currency(db, client_id)
    money = Money.from_major(str(amount), currency)
    weights = [source.target_amount_minor for source in sources]
    parts = money.allocate(weights if any(weights) else [1] * len(sources))
    ledger_service.create_transaction(
        db, client_id=client_id, date=date.today(),
        description=f"Manual contribution: {capsule.name}",
        amount_minor=money.minor, currency=currency,
        legs=[Leg(source.account_id, debit=part.minor, capsule_id=capsule.id)
              for source, part in zip(sources, parts) if part.minor]
             + [Leg(from_account.id, credit=money.minor)],
    )
    db.flush()
    if commit:
        db.commit()
        invalidate_client(client_id)
    return {
        "status": "ok",
        "amount": amount,
        "new_balance": capsule_service.capsule_balance(db, capsule),
    }


def create_product_reserve_pools(
    db: Session, client_id: int, *, commit: bool = True,
) -> list[models.Capsule]:
    capsules = ensure_default_product_reserve_pools(db, client_id)
    if commit:
        db.commit()
        invalidate_client(client_id)
    return capsules


def sync_product_reserves(db: Session, client_id: int, *, commit: bool = True) -> dict:
    result = sync_product_reserve_capsules(db, client_id)
    if commit:
        db.commit()
        invalidate_client(client_id)
    else:
        db.flush()
    return result


def create_goal_capsule(
    db: Session, client_id: int, life_event_id: int, *, commit: bool = True,
) -> models.Capsule:
    goal = get_life_event(db, client_id, life_event_id)
    if not goal:
        raise NotFound("Life event not found")
    capsule = capsule_service.create_capsule_for_goal(db, client_id, goal)
    if commit:
        db.commit()
        db.refresh(capsule)
        invalidate_client(client_id)
    return capsule
