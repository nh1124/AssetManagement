from fastapi import APIRouter, Depends, HTTPException, Query
from ..utils.contribution_schedule import parse_contribution_schedule
from sqlalchemy.orm import Session
from typing import List
import json
from .. import models, schemas, database, dependencies
from ..services.milestone_service import (
    apply_milestones_from_simulation,
    create_milestone as create_milestone_row,
    delete_milestone as delete_milestone_row,
    list_milestones,
    preview_milestones_from_simulation,
    reset_milestones_from_annual_plan,
    update_milestone as update_milestone_row,
)
from ..services.cache_service import get_or_set, invalidate_client


from ..services.strategy_service import get_roadmap_projection

router = APIRouter(
    prefix="/roadmap",
    tags=["Roadmap"],
    dependencies=[Depends(dependencies.get_current_client)]
)


@router.get("/projection")
def read_roadmap_projection(
    years: int = Query(default=30, ge=1, le=60),
    annual_return: float = Query(default=5.0),
    inflation: float = Query(default=2.0),
    monthly_savings: float | None = Query(default=None, ge=0),
    contribution_schedule: str | None = Query(default=None),
    allocation_mode: str = Query(default="weighted", pattern="^(weighted|direct)$"),
    roadmap_interval: str = Query(default="auto", pattern="^(auto|monthly|quarterly|annual)$"),
    include_archived: bool = False,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    parsed_schedule = parse_contribution_schedule(contribution_schedule)
    key = (
        f"client:{current_client.id}:roadmap_projection:{years}:{annual_return}:"
        f"{inflation}:{monthly_savings}:{allocation_mode}:{roadmap_interval}:{include_archived}:"
        f"{json.dumps(parsed_schedule, sort_keys=True)}"
    )
    return get_or_set(
        key,
        300,
        lambda: get_roadmap_projection(
            db=db,
            client_id=current_client.id,
            years=years,
            annual_return=annual_return,
            inflation=inflation,
            monthly_savings=monthly_savings,
            contribution_schedule=parsed_schedule,
            allocation_mode=allocation_mode,
            roadmap_interval=roadmap_interval,
            include_archived=include_archived,
        ),
    )

@router.get("/milestones", response_model=List[schemas.Milestone])
def read_milestones(
    skip: int = 0, 
    limit: int = 100, 
    life_event_id: int | None = Query(None),
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    return list_milestones(db, current_client.id, skip, limit, life_event_id)

@router.post("/milestones", response_model=schemas.Milestone)
def create_milestone(
    milestone: schemas.MilestoneCreate, 
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    try:
        db_milestone = create_milestone_row(db, current_client.id, milestone)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_client(current_client.id)
    return db_milestone

@router.post("/life-events/{life_event_id}/milestones/reset-from-annual", response_model=List[schemas.Milestone])
def reset_life_event_milestones_from_annual(
    life_event_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    try:
        result = reset_milestones_from_annual_plan(db, current_client.id, life_event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    invalidate_client(current_client.id)
    return result


@router.post("/life-events/{life_event_id}/milestones/from-simulation/preview", response_model=schemas.MilestoneSimulationPreview)
def preview_life_event_milestones_from_simulation(
    life_event_id: int,
    payload: schemas.MilestoneSimulationRequest,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    try:
        return preview_milestones_from_simulation(
            db=db,
            client_id=current_client.id,
            life_event_id=life_event_id,
            basis=payload.basis,
            interval=payload.interval,
            mode=payload.mode,
            n_simulations=payload.n_simulations,
            annual_return=payload.annual_return,
            inflation=payload.inflation,
            monthly_savings=payload.monthly_savings,
            contribution_schedule=[item.model_dump(mode='json') for item in payload.contribution_schedule],
            allocation_mode=payload.allocation_mode,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/life-events/{life_event_id}/milestones/from-simulation", response_model=List[schemas.Milestone])
def create_life_event_milestones_from_simulation(
    life_event_id: int,
    payload: schemas.MilestoneSimulationRequest,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    try:
        result = apply_milestones_from_simulation(
            db=db,
            client_id=current_client.id,
            life_event_id=life_event_id,
            basis=payload.basis,
            interval=payload.interval,
            mode=payload.mode,
            n_simulations=payload.n_simulations,
            annual_return=payload.annual_return,
            inflation=payload.inflation,
            monthly_savings=payload.monthly_savings,
            contribution_schedule=[item.model_dump(mode='json') for item in payload.contribution_schedule],
            allocation_mode=payload.allocation_mode,
        )
        invalidate_client(current_client.id)
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.patch("/milestones/{milestone_id}", response_model=schemas.Milestone)
def update_milestone(
    milestone_id: int,
    update: schemas.MilestoneUpdate,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    milestone = update_milestone_row(db, current_client.id, milestone_id, update)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    invalidate_client(current_client.id)
    return milestone


@router.delete("/milestones/{milestone_id}", response_model=schemas.Milestone)
def delete_milestone(
    milestone_id: int, 
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    db_milestone = delete_milestone_row(db, current_client.id, milestone_id)
    if db_milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    invalidate_client(current_client.id)
    return db_milestone
