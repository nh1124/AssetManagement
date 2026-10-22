"""Administrator account management."""
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from ...database import get_db
from ...domain.admin_permissions import ADMINS_MANAGE, PRESETS, validate_permissions
from ...services import admin_auth_service as service
from ...workflows import admin_account_workflow as workflow
from ..auth import attribution, require

router = APIRouter(prefix="/admin/api/admins")


class Create(BaseModel):
    username: str
    preset: Literal["owner", "support", "viewer"] | None = None
    permissions: list[str] | None = None


class Update(BaseModel):
    is_active: bool | None = None
    permissions: list[str] | None = None


@router.get("")
def admins(context=Depends(require(ADMINS_MANAGE)), db=Depends(get_db)):
    return service.list_admins(db)


@router.post("")
def create(body: Create, request: Request, context=Depends(require(ADMINS_MANAGE)), db=Depends(get_db)):
    permissions = validate_permissions(body.permissions or ()) | PRESETS.get(body.preset, frozenset())
    admin, password = workflow.web_admin_create(db, body.username, permissions, **attribution(request, context))
    return {"id": admin.id, "username": admin.username, "temporary_password": password}


@router.patch("/{id}")
def update(id: int, body: Update, request: Request, context=Depends(require(ADMINS_MANAGE)), db=Depends(get_db)):
    admin = workflow.web_admin_update(db, id, **body.model_dump(), **attribution(request, context))
    return {"id": admin.id, "username": admin.username, "is_active": admin.is_active,
            "permissions": sorted(service.permissions_for(db, admin))}


@router.post("/{id}/mfa-reset")
def reset(id: int, request: Request, context=Depends(require(ADMINS_MANAGE)), db=Depends(get_db)):
    return {"temporary_password": workflow.admin_reset_mfa(db, id, **attribution(request, context))}
