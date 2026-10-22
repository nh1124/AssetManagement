"""Installation settings HTTP adapter."""
from typing import Any
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from ...database import get_db
from ...domain.admin_permissions import SETTINGS_MANAGE
from ...services import system_settings_service as service
from ...workflows import admin_account_workflow as workflow
from ..auth import attribution, current_admin, require

router = APIRouter(prefix="/admin/api/settings")


class Value(BaseModel):
    value: Any


@router.get("")
def settings(context=Depends(current_admin), db=Depends(get_db)):
    return service.all(db)


@router.put("/{key}")
def update(key: str, body: Value, request: Request, context=Depends(require(SETTINGS_MANAGE)), db=Depends(get_db)):
    return {"value": workflow.settings_set(db, key, body.value, **attribution(request, context))}
