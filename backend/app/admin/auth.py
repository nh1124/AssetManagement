"""Cookie-only administrator authentication and HTTP capability checks."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..database import get_db
from ..dependencies import request_language
from ..domain.admin_permissions import STEP_UP_REQUIRED
from ..domain.errors import Refused
from ..domain.messages import Message, localize
from ..services import admin_auth_service as service
from ..utils.observability.context import current
from ..workflows import admin_account_workflow as workflow

COOKIE = "am_admin_session"
COOKIE_PATH = "/admin/api"


@dataclass
class AdminContext:
    admin: object
    session: object
    permissions: frozenset


def metadata(request):
    return {"ip": request.client.host if request.client else None, "correlation_id": current().correlation_id}


def attribution(request, context):
    return {"actor": f"admin:{context.admin.id}", "admin_user_id": context.admin.id, **metadata(request)}


def session_details(request):
    return {"ip": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent"), "config": request.app.state.config}


def cookie(response, raw, config=settings):
    response.set_cookie(COOKIE, raw, httponly=True, secure=config.admin_cookie_secure, samesite="strict", path=COOKIE_PATH)


def resolve(request, db, *, stage=None, any_stage=False):
    try:
        admin, row = service.session_admin(db, request.cookies.get(COOKIE), stage=stage, any_stage=any_stage, config=request.app.state.config)
    except service.SessionStageRefused as exc:
        workflow.session_stage_refused(db, exc.admin_user_id, request.url.path, exc.stage, exc.required_stage, **metadata(request))
        raise
    return AdminContext(admin, row, service.permissions_for(db, admin))


def current_admin(request: Request, db=Depends(get_db)):
    return resolve(request, db)


def staged(stage):
    def dependency(request: Request, db=Depends(get_db)):
        return resolve(request, db, stage=stage)
    return dependency



class StepUpRequired(Exception):
    pass


async def step_up_handler(request, exc):
    return JSONResponse(status_code=403, content={"detail": localize(
        Message("Fresh authentication required.", ja="認証コードで再認証してください。"), request_language(request)),
        "code": "step_up_required"})


def check_step_up(context, request, db, permission=None):
    stamp = context.session.stepped_up_at
    if stamp is None or stamp < datetime.utcnow() - timedelta(minutes=5):
        workflow.step_up_required(db, context.admin, request.url.path, permission, **metadata(request))
        raise StepUpRequired()


def require(permission):
    def dependency(request: Request, context=Depends(current_admin), db=Depends(get_db)):
        if permission not in context.permissions:
            workflow.permission_denied(db, context.admin, request.url.path, permission, **metadata(request))
            raise Refused("Permission denied.", ja="この操作の権限がありません。")
        if permission in STEP_UP_REQUIRED:
            check_step_up(context, request, db, permission)
        return context
    dependency.permission = permission
    return dependency


def stepped_admin(request: Request, context=Depends(current_admin), db=Depends(get_db)):
    check_step_up(context, request, db)
    return context
