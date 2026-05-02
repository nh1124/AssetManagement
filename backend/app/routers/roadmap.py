from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas, database, dependencies
from ..services.milestone_service import reset_milestones_from_annual_plan

router = APIRouter(
    prefix="/roadmap",
    tags=["Roadmap"],
    dependencies=[Depends(dependencies.get_current_client)]
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
