"""Goal service boundary.

The public API still exposes legacy /life-events routes, but UI responsibility now treats
these records as the Goal domain. This module keeps routers and reports from depending on
strategy execution services directly.
"""

from datetime import date, datetime
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from .money_storage import minor_fields, money_client_currency

from .. import models, schemas
from ..domain.errors import NotFound, Refused
from ..domain.journal import Leg
from ..domain.money import Money
from .cache_service import invalidate_client
from .capsule_service import capsule_balance, claimed_minor
from .life_scenario_scope import get as get_scenario, selected as selected_scenario
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
    "list_goals_with_progress",
    "copy_events",
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


def list_goals(db: Session, client_id: int, include_archived: bool = False,
               scenario_id: int | None = None) -> list[models.LifeEvent]:
    scenario = selected_scenario(db, client_id, scenario_id)
    if scenario is None:
        return []
    query = db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=scenario.id)
    if not include_archived:
        query = query.filter(models.LifeEvent.archived_at.is_(None))
    return query.all()


def list_goals_with_progress(db: Session, client_id: int, include_archived: bool = False,
                             scenario_id: int | None = None) -> list[dict]:
    scenario = selected_scenario(db, client_id, scenario_id)
    if scenario is None:
        return []
    return get_life_events_with_progress(db, client_id, include_archived=include_archived, scenario_id=scenario.id)


def copy_events(db: Session, client_id: int, source_id: int, target_id: int) -> dict[int, int]:
    from copy import deepcopy

    event_map = {}
    for source in db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=source_id).order_by(models.LifeEvent.id):
        values = {column.name: deepcopy(getattr(source, column.name))
                  for column in models.LifeEvent.__table__.columns if column.name not in {"id", "scenario_id"}}
        row = models.LifeEvent(**values, scenario_id=target_id)
        db.add(row)
        db.flush()
        event_map[source.id] = row.id
    return event_map


def _set_archived(
    db: Session, client_id: int, life_event_id: int, archived: bool, *, commit: bool,
) -> models.LifeEvent | None:
    event = get_life_event(db, client_id, life_event_id)
    if event is None:
        return None
    # Restoring only changes the goal; earlier capsule decisions remain facts.
    event.archived_at = (event.archived_at or datetime.utcnow()) if archived else None
    if commit:
        db.commit()
        db.refresh(event)
        invalidate_client(client_id)
    else:
        db.flush()
    return event


def archive_goal(
    db: Session, client_id: int, life_event_id: int, *,
    capsule_action: Literal["keep", "stop_rules", "release", "detach"] = "keep",
    transfer_account_id: int | None = None, commit: bool = True,
) -> models.LifeEvent | None:
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id, models.LifeEvent.client_id == client_id,
    ).with_for_update().first()
    if event is None:
        return None
    if capsule_action not in {"keep", "stop_rules", "release", "detach"}:
        raise Refused("Unknown capsule_action", status_code=422)
    # Serialize releases on the goal and commit the choice with its journal movements.
    try:
        if capsule_action == "release":
            if transfer_account_id is None:
                raise Refused("transfer_account_id is required for release.", status_code=422)
            _return_goal_claims(db, client_id, event, transfer_account_id, reason="Goal archived")
        elif capsule_action == "detach":
            # Change only the FK: removing from the relationship would delete
            # the capsule through the goal's delete-orphan cascade.
            for capsule in db.query(models.Capsule).filter(
                models.Capsule.client_id == client_id,
                models.Capsule.life_event_id == life_event_id,
            ):
                capsule.life_event_id = None
        elif capsule_action == "stop_rules":
            capsule_ids = [cap.id for cap in event.capsules]
            for rule in db.query(models.CapsuleRule).filter(
                models.CapsuleRule.client_id == client_id,
                models.CapsuleRule.capsule_id.in_(capsule_ids),
            ):
                rule.is_active = False
        _set_archived(db, client_id, life_event_id, True, commit=False)
        if commit:
            db.commit()
    except Exception:
        # A participating caller owns rollback when it also owns the commit.
        if commit:
            db.rollback()
        raise
    if commit:
        db.refresh(event)
        invalidate_client(client_id)
    return event


def unarchive_goal(
    db: Session, client_id: int, life_event_id: int, *, commit: bool = True,
) -> models.LifeEvent | None:
    return _set_archived(db, client_id, life_event_id, False, commit=commit)


def create_goal_record(
    db: Session, client_id: int, payload: schemas.LifeEventCreate, *, commit: bool = True,
) -> models.LifeEvent:
    get_scenario(db, client_id, payload.scenario_id)
    _validate_event_account(db, client_id, payload.account_id)
    db_event = models.LifeEvent(**minor_fields(payload.model_dump(), money_client_currency(db, client_id), 'target_amount'), client_id=client_id)
    db.add(db_event)
    if commit:
        db.commit()
        db.refresh(db_event)
    else:
        db.flush()
    return db_event


def _validate_event_account(db: Session, client_id: int, account_id: int | None) -> None:
    if account_id is not None:
        account = db.get(models.Account, account_id)
        if account is None or account.client_id != client_id:
            raise NotFound("同じクライアントの口座・科目が見つかりません。")


def update_goal(
    db: Session, client_id: int, life_event_id: int, patch: schemas.LifeEventUpdate,
    *, commit: bool = True,
) -> models.LifeEvent | None:
    db_event = get_life_event(db, client_id, life_event_id)
    if db_event is None:
        return None
    _validate_event_account(db, client_id, patch.account_id)
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
            "claims": [
                {"currency": currency, "amount_minor": minor, "amount": Money(minor, currency).to_float()}
                for currency, minor in sorted(claimed_minor(db, client_id, cap.id).items())
            ],
        }
        for cap in db_event.capsules
    ]


def _goal_claims(db: Session, client_id: int, event: models.LifeEvent) -> list[tuple]:
    # Journal attribution survives funding-plan edits, so the plan is not a holdings list.
    return db.query(
        models.Capsule.id, models.Capsule.name, models.JournalEntry.account_id,
        models.Transaction.currency,
        func.sum(models.JournalEntry.debit_minor - models.JournalEntry.credit_minor).label("minor"),
    ).join(models.JournalEntry, models.JournalEntry.capsule_id == models.Capsule.id).join(
        models.Transaction, models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(
        models.Capsule.client_id == client_id, models.Capsule.life_event_id == event.id,
        models.Transaction.client_id == client_id,
    ).group_by(
        models.Capsule.id, models.Capsule.name, models.JournalEntry.account_id, models.Transaction.currency,
    ).having(func.sum(models.JournalEntry.debit_minor - models.JournalEntry.credit_minor) > 0).all()


def _return_goal_claims(
    db: Session, client_id: int, event: models.LifeEvent, transfer_account_id: int, *, reason: str,
) -> None:
    destination = db.get(models.Account, transfer_account_id)
    if destination is None or destination.client_id != client_id:
        raise NotFound("Transfer destination account not found")
    if destination.account_type != "asset" or destination.is_active is False:
        raise Refused("Transfer destination must be an active asset account.", status_code=422)
    claims = _goal_claims(db, client_id, event)
    client_currency = money_client_currency(db, client_id)
    # Validate the whole release before posting any client-currency claim.
    for _, name, _, currency, _ in claims:
        if currency != client_currency:
            raise Refused(
                f"取り置き「{name}」の {currency} の確保額は、このゴールから返金できません。"
                f"ゴールとの紐づけを解除するか、{currency} の口座へその通貨のまま取り崩してください。",
                status_code=422,
            )
    for capsule_id, name, account_id, currency, minor in claims:
        # Running reservation rules here could earmark the returned money again.
        create_transaction(
            db, client_id=client_id, date=date.today(),
            description=f"{reason} – funds returned from Capsule: {name}",
            amount_minor=int(minor), currency=currency,
            legs=[Leg(transfer_account_id, debit=int(minor)),
                  Leg(account_id, credit=int(minor), capsule_id=capsule_id)],
        )


def delete_goal(
    db: Session, client_id: int, life_event_id: int, *,
    transfer_account_id: int | None = None, commit: bool = True,
) -> bool:
    db_event = get_life_event(db, client_id, life_event_id)
    if db_event is None:
        return False

    if _goal_claims(db, client_id, db_event) and transfer_account_id is None:
        raise Refused(
            "transfer_account_id is required because one or more capsules have a non-zero balance.",
            status_code=422,
        )

    accounts_by_capsule = {
        cap.id: [source.account_id for source in cap.funding_sources]
        for cap in db_event.capsules
    }
    if transfer_account_id is not None:
        _return_goal_claims(db, client_id, db_event, transfer_account_id, reason="Goal deleted")

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
