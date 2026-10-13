"""Goal service boundary.

The public API still exposes legacy /life-events routes, but UI responsibility now treats
these records as the Goal domain. This module keeps routers and reports from depending on
strategy execution services directly.
"""

from datetime import date, datetime

from sqlalchemy.orm import Session

from .money_storage import minor_fields, money_client_currency

from .. import models, schemas
from ..domain.errors import NotFound, Refused
from .cache_service import invalidate_client
from .capsule_service import apply_capsule_rules_for_transaction, capsule_balance, claimed_minor
from .ledger_service import create_transaction
from .fx_service import get_client_currency
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
    "archive_goal",
    "unarchive_goal",
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


def list_goals(db: Session, client_id: int, include_archived: bool = False) -> list[models.LifeEvent]:
    query = db.query(models.LifeEvent).filter(models.LifeEvent.client_id == client_id)
    if not include_archived:
        query = query.filter(models.LifeEvent.archived_at.is_(None))
    return query.all()


def _set_archived(
    db: Session, client_id: int, life_event_id: int, archived: bool, *, commit: bool,
) -> models.LifeEvent | None:
    event = get_life_event(db, client_id, life_event_id)
    if event is None:
        return None
    # Calling off a plan preserves capsules, claims and history. Unlike delete,
    # archive never returns funds to another account or removes related rows.
    event.archived_at = (event.archived_at or datetime.utcnow()) if archived else None
    if commit:
        db.commit()
        db.refresh(event)
        invalidate_client(client_id)
    else:
        db.flush()
    return event


def archive_goal(
    db: Session, client_id: int, life_event_id: int, *, commit: bool = True,
) -> models.LifeEvent | None:
    return _set_archived(db, client_id, life_event_id, True, commit=commit)


def unarchive_goal(
    db: Session, client_id: int, life_event_id: int, *, commit: bool = True,
) -> models.LifeEvent | None:
    return _set_archived(db, client_id, life_event_id, False, commit=commit)


def create_goal_record(
    db: Session, client_id: int, payload: schemas.LifeEventCreate, *, commit: bool = True,
) -> models.LifeEvent:
    db_event = models.LifeEvent(**minor_fields(payload.model_dump(), money_client_currency(db, client_id), 'target_amount'), client_id=client_id)
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
    for key, value in minor_fields(patch.model_dump(exclude_unset=True), money_client_currency(db, client_id), "target_amount").items():
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
        if capsule_balance(db, c) > 0
    ]
    if capsules_with_balance and transfer_account_id is None:
        raise Refused(
            "transfer_account_id is required because one or more capsules have a non-zero balance.",
            status_code=422,
        )

    if transfer_account_id is not None:
        dest_account = db.get(models.Account, transfer_account_id)
        if not dest_account or dest_account.client_id != client_id:
            raise NotFound("Transfer destination account not found")

    accounts_by_capsule = {
        cap.id: [source.account_id for source in cap.funding_sources]
        for cap in db_event.capsules
    }
    currency = get_client_currency(db, client_id)
    for cap in capsules_with_balance:
        for account_id in accounts_by_capsule[cap.id]:
            minor = claimed_minor(db, client_id, cap.id, account_id).get(currency, 0)
            if minor <= 0:
                continue
            tx = create_transaction(
                db,
                client_id=client_id,
                date=date.today(),
                description=f"Goal deleted – funds returned from Capsule: {cap.name}",
                amount_minor=minor,
                currency=currency,
                from_account_id=account_id,
                to_account_id=transfer_account_id,
            )
            apply_capsule_rules_for_transaction(db, tx, commit=False)

    account_ids_to_delete = {account_id for ids in accounts_by_capsule.values() for account_id in ids}

    db.delete(db_event)
    db.flush()

    # Removing journal history would leave each transaction's counterparty unbalanced.
    # Keep accounts with history inactive even when no capsule claims remain.
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
