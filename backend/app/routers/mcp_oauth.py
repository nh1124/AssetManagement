"""The backend half of the MCP server's OAuth endpoints (WP35).

The MCP server answers /register, /authorize and /token for AI apps and forwards
the decisions here: who signed in, which connection a code or refresh token
belongs to, and the access token that names it. Only the MCP container calls
these; nginx does not forward /api/auth/mcp/ from outside.

Errors come back in OAuth's shape ({"error": ...}) for the MCP server to relay.
"""
from __future__ import annotations

import re
import time
from datetime import timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..domain.errors import DomainError, detail_for, status_for
from ..services import client_service, mcp_connection_service, mfa_service
from ..utils.jwt import create_mcp_access_token, token_is_current
from ..utils.password import verify_password

router = APIRouter(prefix="/auth/mcp", tags=["mcp-oauth"])

_TOTP = re.compile(r"^\d{6}$")


def _oauth_error(status_code: int, error: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error})


def _domain_error(error: DomainError) -> JSONResponse:
    return JSONResponse(status_code=status_for(error), content=detail_for(error))


# ─── Dynamic Client Registration (RFC 7591) ───────────────

class ClientRegistrationRequest(BaseModel):
    client_name: Optional[str] = None
    redirect_uris: list[str] = []
    grant_types: list[str] = []


def _registration(row) -> dict:
    return {
        "client_id": row.client_id,
        "client_id_issued_at": int(row.created_at.replace(tzinfo=timezone.utc).timestamp()),
        "client_name": row.client_name,
        "redirect_uris": row.redirect_uris,
        "grant_types": row.grant_types,
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


@router.post("/clients", status_code=201)
def register_client(req: ClientRegistrationRequest, db: Session = Depends(get_db)):
    try:
        row = mcp_connection_service.register_client(
            db, client_name=req.client_name, redirect_uris=req.redirect_uris, grant_types=req.grant_types,
        )
    except DomainError as error:
        return _domain_error(error)
    return _registration(row)


@router.get("/clients/{oauth_client_id}")
def get_client(oauth_client_id: str, db: Session = Depends(get_db)):
    row = mcp_connection_service.get_registered_client(db, oauth_client_id)
    if row is None:
        return _oauth_error(404, "invalid_client")
    return _registration(row)


# ─── Authorization ────────────────────────────────────────

class AuthorizeRequest(BaseModel):
    username: str
    password: str
    # A 6-digit authenticator code, or a recovery code.
    factor: str
    oauth_client_id: str
    client_name: Optional[str] = None
    client_source: Literal["cimd", "dcr"]
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str = "S256"
    scope: str = "mcp"
    resource: str
    issuer: str
    allow_refresh: bool = False


def _issuer_allowed(issuer: str) -> bool:
    allowed = settings.allowed_mcp_token_issuers
    return not allowed or issuer.rstrip("/") in allowed


def _sign_in_failed(db: Session, client) -> JSONResponse:
    client_service.record_auth_failure(db, client)
    return _oauth_error(429, "locked") if client_service.is_locked(client) else _oauth_error(401, "invalid")


@router.post("/authorize")
def authorize(req: AuthorizeRequest, db: Session = Depends(get_db)):
    """Sign the person in (password + second factor) and return a code for a new connection.

    The same checks as the app's staged sign-in, ending in a code instead of a
    session: a locked, unapproved or unfinished account cannot connect an AI app.
    """
    if req.code_challenge_method != "S256" or not req.code_challenge or not _issuer_allowed(req.issuer):
        return _oauth_error(400, "invalid_request")
    allow_refresh = req.allow_refresh
    if req.client_source == "dcr":
        registration = mcp_connection_service.get_registered_client(db, req.oauth_client_id)
        if registration is None:
            return _oauth_error(400, "invalid_client")
        allow_refresh = allow_refresh and "refresh_token" in (registration.grant_types or [])

    client = client_service.get_by_username(db, req.username.strip().lower(), active_only=True)
    if client is None:
        return _oauth_error(401, "invalid")
    if client_service.is_locked(client):
        return _oauth_error(429, "locked")
    if not verify_password(req.password, client.password_hash or ""):
        return _sign_in_failed(db, client)
    if client.approval_pending:
        return _oauth_error(403, "approval_pending")
    if client.must_change_password or not mfa_service.mfa_enabled(db, client.id):
        return _oauth_error(403, "setup_required")
    factor = req.factor.strip()
    verified = mfa_service.verify_mfa_factor(
        db, client, **({"code": factor} if _TOTP.match(factor) else {"recovery_code": factor}))
    if not verified:
        return _sign_in_failed(db, client)
    client_service.record_auth_success(db, client)

    try:
        code = mcp_connection_service.start_connection(
            db,
            client_id=client.id,
            oauth_client_id=req.oauth_client_id,
            client_name=req.client_name,
            client_source=req.client_source,
            redirect_uri=req.redirect_uri,
            code_challenge=req.code_challenge,
            scope=req.scope,
            resource=req.resource,
            issuer=req.issuer.rstrip("/"),
            allow_refresh=allow_refresh,
            auth_time_ms=int(time.time() * 1000),
        )
    except DomainError as error:
        return _domain_error(error)
    return {"code": code, "username": client.username}


# ─── Token ────────────────────────────────────────────────

class TokenRequest(BaseModel):
    grant_type: str
    client_id: str
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    code_verifier: Optional[str] = None
    refresh_token: Optional[str] = None


@router.post("/token")
def token(req: TokenRequest, db: Session = Depends(get_db)):
    try:
        if req.grant_type == "authorization_code":
            if not (req.code and req.redirect_uri and req.code_verifier):
                return _oauth_error(400, "invalid_request")
            connection, refresh_token = mcp_connection_service.redeem_code(
                db, code=req.code, oauth_client_id=req.client_id,
                redirect_uri=req.redirect_uri, code_verifier=req.code_verifier,
            )
        elif req.grant_type == "refresh_token":
            if not req.refresh_token:
                return _oauth_error(400, "invalid_request")
            connection, refresh_token = mcp_connection_service.refresh(
                db, refresh_token=req.refresh_token, oauth_client_id=req.client_id,
            )
        else:
            return _oauth_error(400, "unsupported_grant_type")
    except mcp_connection_service.InvalidGrant:
        return _oauth_error(400, "invalid_grant")

    # The account may have changed since the sign-in: a password change or a sign-out
    # everywhere (tokens_valid_after) ends every connection made before it.
    client = client_service.get_active_by_id(db, connection.client_id)
    if (client is None or client.approval_pending
            or not token_is_current({"auth_time_ms": connection.auth_time_ms}, client.tokens_valid_after,
                                    claim="auth_time_ms", required=True)
            or not mfa_service.mfa_enabled(db, client.id)):
        return _oauth_error(400, "invalid_grant")

    expires_in = int(mcp_connection_service.ACCESS_TOKEN_TTL.total_seconds())
    access_token = create_mcp_access_token(
        username=(client.username or "").lower(),
        backend_client_id=client.id,
        oauth_client_id=connection.oauth_client_id,
        scope=connection.scope,
        auth_time_ms=connection.auth_time_ms,
        connection_id=connection.id,
        issuer=connection.issuer,
        resource=connection.resource,
        expires_delta=mcp_connection_service.ACCESS_TOKEN_TTL,
    )
    body = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "scope": connection.scope,
    }
    if refresh_token:
        body["refresh_token"] = refresh_token
    return body
