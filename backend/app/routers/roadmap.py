from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas, database, dependencies

router = APIRouter(
    prefix="/roadmap",
    tags=["Roadmap"],
    dependencies=[Depends(dependencies.get_current_client)]
)

@router.get("/milestones", response_model=List[schemas.Milestone])
def read_milestones(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    milestones = db.query(models.Milestone).filter(models.Milestone.client_id == current_client.id).offset(skip).limit(limit).all()
    return milestones

@router.post("/milestones", response_model=schemas.Milestone)
def create_milestone(
    milestone: schemas.MilestoneCreate, 
    db: Session = Depends(database.get_db),
    current_client: models.Client = Depends(dependencies.get_current_client)
):
    db_milestone = models.Milestone(**milestone.dict(), client_id=current_client.id)
    db.add(db_milestone)
    db.commit()
    db.refresh(db_milestone)
    return db_milestone

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
