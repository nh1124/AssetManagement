from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import household_service

router = APIRouter(prefix="/household-members", tags=["household_members"])


@router.get("", response_model=list[schemas.HouseholdMember])
def get_members(db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return household_service.list_members(db, current_client.id)


@router.post("", response_model=schemas.HouseholdMember)
def create_member(payload: schemas.HouseholdMemberCreate, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return household_service.save_member(db, current_client.id, payload)


@router.put("/{member_id}", response_model=schemas.HouseholdMember)
def update_member(member_id: int, payload: schemas.HouseholdMemberUpdate, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return household_service.save_member(db, current_client.id, payload, member_id)


@router.delete("/{member_id}")
def delete_member(member_id: int, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    household_service.delete_member(db, current_client.id, member_id)
    return {"message": "Deleted"}
