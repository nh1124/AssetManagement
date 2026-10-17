from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from ..utils.contribution_schedule import parse_contribution_schedule
from sqlalchemy.orm import Session
from typing import Optional
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.goal_service import (
    get_life_events_with_progress,
    list_goals,
    update_goal,
    archive_goal,
    unarchive_goal,
    delete_goal,
    list_goal_capsules,
    calculate_overall_goal_probability,
    generate_budget_from_goals,
    get_strategy_dashboard,
)
from ..workflows.goal_workflow import create_goal
from ..services import life_event_graph, life_event_conditions

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
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return life_event_graph.list_links(db, current_client.id)


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


@router.get("/")
def get_life_events(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all life events for current client."""
    return list_goals(db, current_client.id, include_archived=include_archived)

@router.get("/with-progress")
def get_life_events_progress(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all life events with calculated progress for current client."""
    return get_life_events_with_progress(db, client_id=current_client.id, include_archived=include_archived)

@router.get("/goal-probability")
def get_goal_probability(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get overall goal probability calculation for current client."""
    return calculate_overall_goal_probability(db, client_id=current_client.id)

@router.get("/dashboard")
def get_dashboard(
    annual_return: float = Query(5.0, description="Annual return rate (%)"),
    inflation: float = Query(2.0, description="Inflation rate (%)"),
    monthly_savings: float = Query(50000.0, description="Monthly savings amount"),
    contribution_schedule: Optional[str] = Query(None, description="JSON contribution schedule"),
    allocation_mode: str = Query("weighted", pattern="^(weighted|direct)$"),
    roadmap_interval: str = Query("auto", description="Roadmap granularity: auto|monthly|quarterly|annual"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get comprehensive strategy dashboard with events, projections, and unallocated assets."""
    return get_strategy_dashboard(
        db,
        client_id=current_client.id,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=parse_contribution_schedule(contribution_schedule),
        allocation_mode=allocation_mode,
        roadmap_interval=roadmap_interval,
    )

@router.post("/")
def create_life_event(
    life_event: schemas.LifeEventCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create a new life event for current client."""
    return create_goal(db, current_client.id, life_event)

@router.put("/{event_id}")
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

@router.post("/{event_id}/archive", response_model=schemas.LifeEvent)
def archive_life_event(
    event_id: int,
    payload: schemas.GoalArchiveRequest = schemas.GoalArchiveRequest(),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    event = archive_goal(
        db, current_client.id, event_id,
        capsule_action=payload.capsule_action,
        transfer_account_id=payload.transfer_account_id,
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Life event not found")
    return event


@router.post("/{event_id}/unarchive", response_model=schemas.LifeEvent)
def unarchive_life_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    event = unarchive_goal(db, current_client.id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Life event not found")
    return event


@router.get("/{event_id}/capsules")
def get_capsules_for_goal(
    event_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    result = list_goal_capsules(db, current_client.id, event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Life event not found")
    return result

@router.delete("/{event_id}")
def delete_life_event(
    event_id: int,
    transfer_account_id: Optional[int] = Query(None, description="Transfer capsule balances to this account before deletion"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    if not delete_goal(db, current_client.id, event_id, transfer_account_id=transfer_account_id):
        raise HTTPException(status_code=404, detail="Life event not found")
    return {"message": "Deleted"}

@router.get("/generate-budget/{month}")
def generate_budget(
    month: str, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Generate budget template from life event goals for current client."""
    return generate_budget_from_goals(db, month, client_id=current_client.id)


