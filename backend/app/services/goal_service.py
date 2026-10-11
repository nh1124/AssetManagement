"""Goal service boundary.

The public API still exposes legacy /life-events routes, but UI responsibility now treats
these records as the Goal domain. This module keeps routers and reports from depending on
strategy execution services directly.
"""

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from .cache_service import invalidate_client
from .capsule_service import apply_capsule_rules_for_transaction, capsule_balance
from .ledger_service import create_transaction
from .strategy_service import (
    calculate_overall_goal_probability,
    generate_budget_from_goals,
    get_life_events_with_progress,
    get_strategy_dashboard,
    summarize_goal_funding_gap,
)

__all__ = [
    "list_goals",
    "create_goal_record",
    "update_goal",
    "delete_goal",
    "list_goal_capsules",
    "calculate_overall_goal_probability",
    "generate_budget_from_goals",
    "get_life_events_with_progress",
    "get_life_event",
    "get_strategy_dashboard",
    "summarize_goal_funding_gap",
]


def get_life_event(db: Session, client_id: int, life_event_id: int) -> models.LifeEvent | None:
    return db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == client_id,
    ).first()


def list_goals(db: Session, client_id: int) -> list[models.LifeEvent]:
    return db.query(models.LifeEvent).filter(models.LifeEvent.client_id == client_id).all()


def create_goal_record(
    db: Session, client_id: int, payload: schemas.LifeEventCreate, *, commit: bool = True,
) -> models.LifeEvent:
    db_event = models.LifeEvent(**payload.model_dump(), client_id=client_id)
    db.add(db_event)
    if commit:
        db.commit()
        db.refresh(db_event)
    else:
        db.flush()
    return db_event


def update_goal(
    db: Session, client_id: int, life_event_id: int, patch: schemas.LifeEventUpdate,
    *, commit: bool = True,
) -> models.LifeEvent | None:
    db_event = get_life_event(db, client_id, life_event_id)
    if db_event is None:
        return None
    for key, value in patch.model_dump(exclude_unset=True).items():
        setattr(db_event, key, value)
    if commit:
        db.commit()
        db.refresh(db_event)
        invalidate_client(client_id)
    else:
        db.flush()
    return db_event


def list_goal_capsules(db: Session, client_id: int, life_event_id: int) -> list[dict] | None:
    db_event = get_life_event(db, client_id, life_event_id)
    if db_event is None:
        return None
    return [
        {
            "id": cap.id,
            "name": cap.name,
            "current_balance": capsule_balance(db, cap),
            "account_id": cap.account_id,
        }
        for cap in db_event.capsules
    ]


def delete_goal(
    db: Session, client_id: int, life_event_id: int, *,
    transfer_account_id: int | None = None, commit: bool = True,
) -> bool:
    db_event = get_life_event(db, client_id, life_event_id)
    if db_event is None:
        return False

    capsules_with_balance = [
        c for c in db_event.capsules
        if c.account_id is not None and capsule_balance(db, c) > 0
    ]
    if capsules_with_balance and transfer_account_id is None:
        raise HTTPException(
            status_code=422,
            detail="transfer_account_id is required because one or more capsules have a non-zero balance."
        )

    if transfer_account_id is not None:
        dest_account = db.get(models.Account, transfer_account_id)
        if not dest_account or dest_account.client_id != client_id:
            raise HTTPException(status_code=404, detail="Transfer destination account not found")

    for cap in capsules_with_balance:
        bal = capsule_balance(db, cap)
        tx = create_transaction(
            db,
            client_id=client_id,
            date=date.today(),
            description=f"Goal deleted – funds returned from Capsule: {cap.name}",
            amount=bal,
            currency="JPY",
            from_account_id=cap.account_id,
            to_account_id=transfer_account_id,
        )
        apply_capsule_rules_for_transaction(db, tx, commit=False)

    account_ids_to_delete = [
        c.account_id for c in db_event.capsules if c.account_id is not None
    ]

    # Nullify account_id on capsules so accounts can be deleted without FK violation
    for cap in db_event.capsules:
        cap.account_id = None
    db.flush()

    db.delete(db_event)
    db.flush()

    # Removing journal history would leave each transaction's counterparty unbalanced.
    # Keep accounts with history inactive even when capsule holdings are empty.
    for account_id in account_ids_to_delete:
        account = db.get(models.Account, account_id)
        if not account:
            continue
        has_history = db.query(models.JournalEntry).filter(
            models.JournalEntry.account_id == account_id
        ).first() is not None
        if has_history:
            account.is_active = False
            continue
        db.delete(account)

    if commit:
        db.commit()
        invalidate_client(client_id)
    else:
        db.flush()
    return True
