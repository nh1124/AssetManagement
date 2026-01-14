from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.strategy_service import get_life_events_with_progress, calculate_overall_goal_probability, generate_budget_from_goals

router = APIRouter(prefix="/life-events", tags=["life_events"])

@router.get("/")
def get_life_events(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all life events for current client."""
    return db.query(models.LifeEvent).filter(models.LifeEvent.client_id == current_client.id).all()

@router.get("/with-progress")
def get_life_events_progress(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get all life events with calculated progress for current client."""
    return get_life_events_with_progress(db, client_id=current_client.id)

@router.get("/goal-probability")
def get_goal_probability(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get overall goal probability calculation for current client."""
    return calculate_overall_goal_probability(db, client_id=current_client.id)

@router.post("/")
def create_life_event(
    life_event: schemas.LifeEventCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create a new life event for current client."""
    db_event = models.LifeEvent(**life_event.model_dump(), client_id=current_client.id)
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@router.put("/{event_id}")
def update_life_event(
    event_id: int, 
    life_event: schemas.LifeEventCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Update a life event belonging to current client."""
    db_event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == event_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    
    if not db_event:
        raise HTTPException(status_code=404, detail="Life event not found")
        
    for key, value in life_event.model_dump().items():
        setattr(db_event, key, value)
    db.commit()
    db.refresh(db_event)
    return db_event

@router.delete("/{event_id}")
def delete_life_event(
    event_id: int, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Delete a life event belonging to current client."""
    db_event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == event_id,
        models.LifeEvent.client_id == current_client.id
    ).first()
    
    if not db_event:
        raise HTTPException(status_code=404, detail="Life event not found")
        
    db.delete(db_event)
    db.commit()
    return {"message": "Deleted"}

@router.get("/generate-budget/{month}")
def generate_budget(
    month: str, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Generate budget template from life event goals for current client."""
    return generate_budget_from_goals(db, month, client_id=current_client.id)
