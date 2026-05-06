from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
import json
from .. import models, schemas, database, dependencies
from ..services.milestone_service import (
    apply_milestones_from_simulation,
    preview_milestones_from_simulation,
    reset_milestones_from_annual_plan,
)


def _parse_contribution_schedule(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid contribution_schedule JSON") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="contribution_schedule must be a list")
    return [item for item in value if isinstance(item, dict)]
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
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client),
):
    return get_roadmap_projection(
        db=db,
        client_id=current_client.id,
        years=years,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=_parse_contribution_schedule(contribution_schedule),
        allocation_mode=allocation_mode,
    )

@router.get("/milestones", response_model=List[schemas.Milestone])
def read_milestones(
    skip: int = 0, 
    limit: int = 100, 
    life_event_id: int | None = Query(None),
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    query = db.query(models.Milestone).filter(models.Milestone.client_id == current_client.id)
    if life_event_id is not None:
        query = query.filter(models.Milestone.life_event_id == life_event_id)
    milestones = query.order_by(models.Milestone.date, models.Milestone.id).offset(skip).limit(limit).all()
    return milestones

@router.post("/milestones", response_model=schemas.Milestone)
def create_milestone(
    milestone: schemas.MilestoneCreate, 
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    if milestone.life_event_id is not None:
        event = db.query(models.LifeEvent).filter(
            models.LifeEvent.id == milestone.life_event_id,
            models.LifeEvent.client_id == current_client.id,
        ).first()
        if not event:
            raise HTTPException(status_code=404, detail="Life event not found")

    db_milestone = models.Milestone(**milestone.model_dump(), client_id=current_client.id)
    db.add(db_milestone)
    db.commit()
    db.refresh(db_milestone)
    return db_milestone

@router.post("/life-events/{life_event_id}/milestones/reset-from-annual", response_model=List[schemas.Milestone])
def reset_life_event_milestones_from_annual(
    life_event_id: int,
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == current_client.id,
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")
    return reset_milestones_from_annual_plan(db, current_client.id, life_event_id)


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
        return apply_milestones_from_simulation(
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

@router.delete("/milestones/{milestone_id}", response_model=schemas.Milestone)
def delete_milestone(
    milestone_id: int, 
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    db_milestone = db.query(models.Milestone).filter(models.Milestone.id == milestone_id, models.Milestone.client_id == current_client.id).first()
    if db_milestone is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    db.delete(db_milestone)
    db.commit()
    return db_milestone
