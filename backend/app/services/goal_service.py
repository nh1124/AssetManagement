"""Own life-event records and the shared read scope for the adopted plan.

Projection consumers depend on this owner so scenario copies cannot become real goals.
A life event is a story fact; the earmark made for a goal event is the capsule service's.
"""

from sqlalchemy.orm import Query, Session

from .money_storage import minor_fields, money_client_currency

from .. import models, schemas
from ..domain.errors import Refused
from .cache_service import invalidate_client
from .life_scenario_scope import get as get_scenario, selected as selected_scenario

__all__ = [
    "list_goals",
    "goal_events_query",
    "copy_events",
    "create_goal_record",
    "update_goal",
    "delete_goal",
    "get_life_event",
]


def goal_events_query(db: Session, client_id: int) -> Query:
    """Read the adopted plan without counting copies in other scenarios."""
    scenario_ids = db.query(models.LifeScenario.id).filter_by(client_id=client_id, is_goal=True)
    # A subquery also yields no events when the client has no adopted scenario.
    return db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id,
        models.LifeEvent.scenario_id.in_(scenario_ids),
    )


def get_life_event(db: Session, client_id: int, life_event_id: int) -> models.LifeEvent | None:
    return db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == client_id,
    ).first()


def list_goals(db: Session, client_id: int, scenario_id: int | None = None) -> list[models.LifeEvent]:
    scenario = selected_scenario(db, client_id, scenario_id)
    if scenario is None:
        return []
    return db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=scenario.id).order_by(
        models.LifeEvent.target_date, models.LifeEvent.id).all()


def copy_events(db: Session, client_id: int, source_id: int, target_id: int) -> dict[int, int]:
    """Copy a scenario's events; a copied repayment repays the copy of its borrowing."""
    event_map = {}
    copies = []
    for source in db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=source_id).order_by(models.LifeEvent.id):
        values = {column.name: getattr(source, column.name)
                  for column in models.LifeEvent.__table__.columns if column.name not in {"id", "scenario_id", "borrowing_event_id"}}
        row = models.LifeEvent(**values, scenario_id=target_id)
        db.add(row)
        db.flush()
        event_map[source.id] = row.id
        copies.append((source, row))
    for source, row in copies:
        row.borrowing_event_id = event_map.get(source.borrowing_event_id)
    db.flush()
    return event_map


# Fields a patch may not clear: sent as null they mean "unchanged".
_REQUIRED = {"direction", "condition_mode", "name", "target_date", "target_amount", "priority"}


def _settle(db: Session, client_id: int, event: models.LifeEvent) -> None:
    """Check the event as it will be saved, and clear what its kind does not use."""
    event.interest_rate = (event.interest_rate or 0.0) if event.direction == "borrowing" else None
    if event.direction == "repayment":
        borrowing = get_life_event(db, client_id, event.borrowing_event_id) if event.borrowing_event_id else None
        if borrowing is None or borrowing.direction != "borrowing" or borrowing.scenario_id != event.scenario_id or borrowing.id == event.id:
            raise Refused("同じシナリオの借入イベントを選んでください。", status_code=422)
        event.repeat_count = event.repeat_count or 1
    else:
        event.borrowing_event_id = None
        event.repeat_count = None
    if event.id is not None and event.direction != "borrowing" and db.query(models.LifeEvent.id).filter_by(
            client_id=client_id, borrowing_event_id=event.id).first():
        raise Refused("この借入を返す返済イベントがあります。先に返済イベントを変更してください。", status_code=422)


def create_goal_record(
    db: Session, client_id: int, payload: schemas.LifeEventCreate, *, commit: bool = True,
) -> models.LifeEvent:
    get_scenario(db, client_id, payload.scenario_id)
    db_event = models.LifeEvent(**minor_fields(payload.model_dump(), money_client_currency(db, client_id), 'target_amount'), client_id=client_id)
    _settle(db, client_id, db_event)
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
    values = {key: value for key, value in patch.model_dump(exclude_unset=True).items()
              if not (key in _REQUIRED and value is None)}
    for key, value in minor_fields(values, money_client_currency(db, client_id), "target_amount").items():
        setattr(db_event, key, value)
    try:
        _settle(db, client_id, db_event)
    except Exception:
        db.rollback()
        raise
    if commit:
        db.commit()
        db.refresh(db_event)
        invalidate_client(client_id)
    else:
        db.flush()
    return db_event


def delete_goal(db: Session, client_id: int, life_event_id: int) -> bool:
    """Delete the story fact; its links, conditions and 資金の割り当て go with it, its earmark stays."""
    db_event = get_life_event(db, client_id, life_event_id)
    if db_event is None:
        return False
    db.delete(db_event)
    db.commit()
    invalidate_client(client_id)
    return True
