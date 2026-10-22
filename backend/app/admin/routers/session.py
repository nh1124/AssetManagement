"""Administrator sign-in state machine HTTP adapter."""
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from ...database import get_db
from ...services import admin_auth_service as service
from ...workflows import admin_account_workflow as workflow
from ..auth import (COOKIE, COOKIE_PATH, attribution, cookie, current_admin, metadata,
                    session_details, staged)

router = APIRouter(prefix="/admin/api/session")


class Login(BaseModel):
    username: str
    password: str
    code: str | None = None


class Password(BaseModel):
    new_password: str


class Code(BaseModel):
    code: str


def result(response, values, config):
    admin, raw, stage, *extra = values
    cookie(response, raw, config)
    return {"stage": stage, "admin": {"username": admin.username}, **(extra[0] if extra else {})}


@router.post("")
def login(body: Login, request: Request, response: Response, db=Depends(get_db)):
    values = workflow.session_operation(db, "session.login", lambda: service.sign_in(
        db, body.username, body.password, body.code, **session_details(request)), **metadata(request))
    return result(response, values, request.app.state.config)


def transition(request, response, db, context, endpoint, **values):
    outcome = workflow.session_operation(db, "session." + endpoint, lambda: service.transition(
        db, context.admin, context.session, endpoint, **values, **session_details(request)), **attribution(request, context))
    return result(response, outcome, request.app.state.config)


@router.post("/password")
def password(body: Password, request: Request, response: Response, context=Depends(staged("password_change")), db=Depends(get_db)):
    return transition(request, response, db, context, "password", new_password=body.new_password)


@router.post("/code")
def code(body: Code, request: Request, response: Response, context=Depends(staged("mfa")), db=Depends(get_db)):
    return transition(request, response, db, context, "code", code=body.code)


@router.post("/mfa-setup/start")
def setup_start(request: Request, response: Response, context=Depends(staged("mfa_setup")), db=Depends(get_db)):
    return transition(request, response, db, context, "setup_start")


@router.post("/mfa-setup/verify")
def setup_verify(body: Code, request: Request, response: Response, context=Depends(staged("mfa_setup")), db=Depends(get_db)):
    return transition(request, response, db, context, "setup_verify", code=body.code)


@router.post("/step-up")
def step_up(body: Code, request: Request, context=Depends(current_admin), db=Depends(get_db)):
    workflow.session_operation(db, "session.step_up", lambda: service.step_up(
        db, context.admin, context.session, body.code), **attribution(request, context))
    return {"ok": True}


@router.delete("")
def logout(request: Request, response: Response, context=Depends(current_admin), db=Depends(get_db)):
    workflow.session_operation(db, "session.logout", lambda: service.revoke_session(
        db, context.session, commit=False), **attribution(request, context))
    response.delete_cookie(COOKIE, path=COOKIE_PATH, httponly=True, secure=request.app.state.config.admin_cookie_secure, samesite="strict")
    return {"ok": True}
