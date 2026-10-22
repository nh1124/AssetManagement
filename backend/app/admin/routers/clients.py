"""Safe client summaries and audited account operations."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from ...database import get_db
from ...domain.admin_permissions import ACCOUNTS_READ, ACCOUNTS_MANAGE, ACCOUNTS_CREDENTIALS, HEALTH_READ, HEALTH_REPAIR
from ...services import client_service as service
from ...workflows import admin_account_workflow as workflow
from ..auth import attribution, require

router = APIRouter(prefix="/admin/api/clients")


class Create(BaseModel):
    username: str
    name: str
    email: str | None = None


class Suspend(BaseModel):
    reason: str


@router.get("")
def clients(status: str | None = None, query: str | None = None, limit: int = 100, offset: int = 0,
            context=Depends(require(ACCOUNTS_READ)), db=Depends(get_db)):
    return service.admin_list(db, status=status, query=query, limit=limit, offset=offset)


@router.get("/{id}")
def client(id: int, context=Depends(require(ACCOUNTS_READ)), db=Depends(get_db)):
    return service.admin_summary(db, service.get_by_id(db, id))


@router.post("")
def create(body: Create, request: Request, context=Depends(require(ACCOUNTS_MANAGE)), db=Depends(get_db)):
    client, password = workflow.client_create(db, **body.model_dump(), **attribution(request, context))
    return {"id": client.id, "username": client.username, "temporary_password": password}


@router.post("/{id}/suspend")
def suspend(id: int, body: Suspend, request: Request, context=Depends(require(ACCOUNTS_MANAGE)), db=Depends(get_db)):
    workflow.client_suspend(db, id, body.reason, **attribution(request, context))
    return {"ok": True}


@router.post("/{id}/reactivate")
def reactivate(id: int, request: Request, context=Depends(require(ACCOUNTS_MANAGE)), db=Depends(get_db)):
    workflow.client_reactivate(db, id, **attribution(request, context))
    return {"ok": True}


@router.post("/{id}/approve")
def approve(id: int, request: Request, context=Depends(require(ACCOUNTS_MANAGE)), db=Depends(get_db)):
    workflow.client_approve(db, id, **attribution(request, context))
    return {"ok": True}


@router.post("/{id}/unlock")
def unlock(id: int, request: Request, context=Depends(require(ACCOUNTS_MANAGE)), db=Depends(get_db)):
    workflow.client_unlock(db, id, **attribution(request, context))
    return {"ok": True}


@router.post("/{id}/sign-out")
def sign_out(id: int, request: Request, context=Depends(require(ACCOUNTS_MANAGE)), db=Depends(get_db)):
    workflow.client_sign_out(db, id, **attribution(request, context))
    return {"ok": True}


@router.post("/{id}/password-reset")
def password_reset(id: int, request: Request, context=Depends(require(ACCOUNTS_CREDENTIALS)), db=Depends(get_db)):
    return {"temporary_password": workflow.client_reset_password(db, id, **attribution(request, context))}


@router.post("/{id}/mfa-reset")
def mfa_reset(id: int, request: Request, context=Depends(require(ACCOUNTS_CREDENTIALS)), db=Depends(get_db)):
    return {"temporary_password": workflow.client_reset_mfa(db, id, **attribution(request, context))}


@router.get("/{id}/health")
def health(id: int, request: Request, context=Depends(require(HEALTH_READ)), db=Depends(get_db)):
    return workflow.health_check(db, id, **attribution(request, context))


@router.post("/{id}/health/repair")
def repair(id: int, request: Request, context=Depends(require(HEALTH_REPAIR)), db=Depends(get_db)):
    return workflow.health_repair(db, id, **attribution(request, context))
