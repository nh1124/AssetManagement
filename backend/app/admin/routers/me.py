"""The signed-in administrator's profile and sessions."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from ...database import get_db
from ...services import admin_auth_service as service
from ...workflows import admin_account_workflow as workflow
from ..auth import attribution, current_admin, stepped_admin

router = APIRouter(prefix="/admin/api/me")


class Password(BaseModel):
    current_password: str
    new_password: str


@router.get("")
def me(context=Depends(current_admin)):
    return {"username": context.admin.username, "permissions": sorted(context.permissions),
            "session": service.session_summary(context.session)}


@router.get("/sessions")
def sessions(request: Request, context=Depends(current_admin), db=Depends(get_db)):
    return service.own_sessions(db, context.admin, config=request.app.state.config)


@router.delete("/sessions/{id}")
def revoke(id: str, request: Request, context=Depends(current_admin), db=Depends(get_db)):
    workflow.session_operation(db, "session.revoke", lambda: service.revoke_own_session(
        db, context.admin, id, commit=False), **attribution(request, context))
    return {"ok": True}


@router.post("/password")
def password(body: Password, request: Request, context=Depends(stepped_admin), db=Depends(get_db)):
    workflow.session_operation(db, "admin.password", lambda: service.change_own_password(
        db, context.admin, context.session, body.current_password, body.new_password), **attribution(request, context))
    return {"ok": True}
