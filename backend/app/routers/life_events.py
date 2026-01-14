from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/life-events", tags=["life-events"])

@router.get("/", response_model=List[schemas.LifeEvent])
def get_life_events(db: Session = Depends(get_db)):
    return db.query(models.LifeEvent).all()

@router.post("/", response_model=schemas.LifeEvent)
def create_life_event(event: schemas.LifeEventCreate, db: Session = Depends(get_db)):
    db_event = models.LifeEvent(**event.model_dump())
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event
