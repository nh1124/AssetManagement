"""Own life-event records and the shared read scope for the adopted plan.

Projection consumers depend on this owner so scenario copies cannot become real goals.
A life event is a story fact only: earmark tracking lives in goal_earmark_service.
"""

from sqlalchemy.orm import Query, Session

from .money_storage import minor_fields, money_client_currency

from .. import models, schemas
from ..domain.errors import NotFound
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
    event_map = {}
    for source in db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=source_id).order_by(models.LifeEvent.id):
        values = {column.name: getattr(source, column.name)
                  for column in models.LifeEvent.__table__.columns if column.name not in {"id", "scenario_id"}}
        row = models.LifeEvent(**values, scenario_id=target_id)
        db.add(row)
        db.flush()
        event_map[source.id] = row.id
    return event_map


def _validate_event_account(db: Session, client_id: int, account_id: int | None) -> None:
    if account_id is not None:
        account = db.get(models.Account, account_id)
        if account is None or account.client_id != client_id:
            raise NotFound("同じクライアントの口座・科目が見つかりません。")


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


def delete_goal(db: Session, client_id: int, life_event_id: int) -> bool:
    """Delete the story fact; its links, conditions and earmark links go with it, the earmarks stay."""
    db_event = get_life_event(db, client_id, life_event_id)
    if db_event is None:
        return False
    db.delete(db_event)
    db.commit()
    invalidate_client(client_id)
    return True
