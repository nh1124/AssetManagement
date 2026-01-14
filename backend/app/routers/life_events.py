from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..database import get_db
from ..services.strategy_service import get_life_events_with_progress, calculate_overall_goal_probability, generate_budget_from_goals

router = APIRouter(prefix="/life-events", tags=["life_events"])

@router.get("/")
def get_life_events(db: Session = Depends(get_db)):
    """Get all life events."""
    return db.query(models.LifeEvent).all()

@router.get("/with-progress")
def get_life_events_progress(db: Session = Depends(get_db)):
    """Get all life events with calculated progress and probability."""
    return get_life_events_with_progress(db)

@router.get("/goal-probability")
def get_goal_probability(db: Session = Depends(get_db)):
    """Get overall goal probability calculation."""
    return calculate_overall_goal_probability(db)

@router.post("/")
def create_life_event(life_event: schemas.LifeEventCreate, db: Session = Depends(get_db)):
    """Create a new life event."""
    db_event = models.LifeEvent(**life_event.model_dump())
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@router.put("/{event_id}")
def update_life_event(event_id: int, life_event: schemas.LifeEventCreate, db: Session = Depends(get_db)):
    """Update a life event."""
    db_event = db.query(models.LifeEvent).filter(models.LifeEvent.id == event_id).first()
    if db_event:
        for key, value in life_event.model_dump().items():
            setattr(db_event, key, value)
        db.commit()
        db.refresh(db_event)
    return db_event

@router.delete("/{event_id}")
def delete_life_event(event_id: int, db: Session = Depends(get_db)):
    """Delete a life event."""
    db_event = db.query(models.LifeEvent).filter(models.LifeEvent.id == event_id).first()
    if db_event:
        db.delete(db_event)
        db.commit()
        return {"message": "Deleted"}
    return {"message": "Not found"}

@router.get("/generate-budget/{month}")
def generate_budget(month: str, db: Session = Depends(get_db)):
    """Generate budget template from life event goals."""
    return generate_budget_from_goals(db, month)
