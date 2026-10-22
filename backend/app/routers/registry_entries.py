from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..domain.messages import Message
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.registry_service import list_entries
from ..workflows import registry_workflow

from ..workflows import plan_reflection_workflow
router = APIRouter(prefix="/auto-transactions", tags=["auto-transactions"])


def enrich_entry(entry):
    result = schemas.RegistryEntry.model_validate(entry).model_dump()
    for key in ("source", "destination", "budget"):
        account = getattr(entry, f"{key}_account")
        result[f"{key}_account_name"] = account.name if account else None
    return result


@router.get("/", response_model=list[schemas.RegistryEntry])
def list_automatic_transactions(db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    return [enrich_entry(entry) for entry in list_entries(db, current_client.id)]


@router.post("/", response_model=schemas.RegistryEntry)
def create_automatic_transaction(payload: schemas.RegistryEntryCreate, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    result = enrich_entry(registry_workflow.save(db, current_client.id, payload.model_dump()))
    plan_reflection_workflow.after_change(db, current_client.id)
    return result


@router.put("/{entry_id}", response_model=schemas.RegistryEntry)
def update_automatic_transaction(entry_id: int, payload: schemas.RegistryEntryCreate, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    entry = registry_workflow.save(db, current_client.id, payload.model_dump(), entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=Message("自動取引が見つかりません", en="Automatic transaction not found"))
    result = enrich_entry(entry)
    plan_reflection_workflow.after_change(db, current_client.id)
    return result


@router.delete("/{entry_id}", status_code=204)
def delete_automatic_transaction(entry_id: int, db: Session = Depends(get_db), current_client: models.Client = Depends(get_current_client)):
    if not registry_workflow.delete(db, current_client.id, entry_id):
        raise HTTPException(status_code=404, detail=Message("自動取引が見つかりません", en="Automatic transaction not found"))
    plan_reflection_workflow.after_change(db, current_client.id)
