"""Read scenario ownership without depending on projection or graph services."""
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import NotFound


def lock_client(db: Session, client_id: int) -> None:
    # Goal switching and attaching real money must observe the same goal.
    if db.query(models.Client).filter_by(id=client_id).with_for_update().first() is None:
        raise NotFound("クライアントが見つかりません。")


def get(db: Session, client_id: int, scenario_id: int) -> models.LifeScenario:
    scenario = db.query(models.LifeScenario).filter_by(client_id=client_id, id=scenario_id).first()
    if scenario is None:
        raise NotFound("シナリオが見つかりません。")
    return scenario


def get_goal(db: Session, client_id: int) -> models.LifeScenario | None:
    return db.query(models.LifeScenario).filter_by(client_id=client_id, is_goal=True).first()


def selected(db: Session, client_id: int, scenario_id: int | None) -> models.LifeScenario | None:
    return get_goal(db, client_id) if scenario_id is None else get(db, client_id, scenario_id)
