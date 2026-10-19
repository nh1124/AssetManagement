from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import goal_earmark_service, life_event_conditions, life_event_graph
from ..services.goal_service import create_goal_record, delete_goal, list_goals, update_goal

router = APIRouter(prefix="/life-events", tags=["life_events"])


@router.get("/conditions")
def get_all_conditions(
    as_of: date | None = None,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return life_event_conditions.evaluate_all(db, current_client.id, as_of=as_of)


@router.get("/{event_id}/conditions")
def get_conditions(
    event_id: int, as_of: date | None = None,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return life_event_conditions.evaluate(db, current_client.id, event_id, as_of=as_of)


@router.post("/{event_id}/conditions", response_model=schemas.LifeEventCondition)
def create_condition(
    event_id: int, payload: schemas.LifeEventConditionCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return life_event_conditions.create_condition(db, current_client.id, event_id, payload)


@router.put("/{event_id}/conditions/{condition_id}", response_model=schemas.LifeEventCondition)
def update_condition(
    event_id: int, condition_id: int, payload: schemas.LifeEventConditionCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return life_event_conditions.update_condition(db, current_client.id, event_id, condition_id, payload)


@router.delete("/{event_id}/conditions/{condition_id}")
def delete_condition(
    event_id: int, condition_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    life_event_conditions.delete_condition(db, current_client.id, event_id, condition_id)
    return {"message": "Deleted"}


@router.get("/links", response_model=list[schemas.LifeEventLink])
def get_links(
    scenario_id: int | None = None,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return life_event_graph.list_links(db, current_client.id, scenario_id=scenario_id)


@router.post("/links", response_model=schemas.LifeEventLink)
def create_link(
    payload: schemas.LifeEventLinkCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return life_event_graph.create_link(db, current_client.id, **payload.model_dump())


@router.delete("/links/{link_id}")
def delete_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    life_event_graph.delete_link(db, current_client.id, link_id)
    return {"message": "Deleted"}


@router.get("/", response_model=list[schemas.LifeEvent])
def get_life_events(
    scenario_id: int | None = None,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """The goal scenario's events, or another scenario's."""
    return list_goals(db, current_client.id, scenario_id=scenario_id)


@router.get("/with-progress")
def get_life_events_progress(
    scenario_id: int | None = None,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Events with their linked earmarks (実績管理の設定) and the funding those give."""
    return goal_earmark_service.events_with_progress(db, current_client.id, scenario_id)


@router.post("/", response_model=schemas.LifeEvent)
def create_life_event(
    life_event: schemas.LifeEventCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    return create_goal_record(db, current_client.id, life_event)


@router.put("/{event_id}", response_model=schemas.LifeEvent)
def update_life_event(
    event_id: int,
    life_event: schemas.LifeEventUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    updated = update_goal(db, current_client.id, event_id, life_event)
    if updated is None:
        raise HTTPException(status_code=404, detail="Life event not found")
    return updated


@router.delete("/{event_id}")
def delete_life_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    if not delete_goal(db, current_client.id, event_id):
        raise HTTPException(status_code=404, detail="Life event not found")
    return {"message": "Deleted"}
