"""WP35: the MCP server's OAuth state lives in the backend (owner 2026-10-24, C1-C5).

DCR registrations and connections survive the MCP container; a connection is
ended on its own and its tokens stop at the next request; refresh tokens rotate,
and a replay ends the connection.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import pyotp
import pytest
from fastapi import Depends, FastAPI
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.config import settings
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.main import app as main_app
from app.routers import ai_operations, auth, mcp_oauth
from app.security import encrypt_key
from app.services import ai_policy_service, mcp_connection_service as connections
from app.utils.jwt import create_typed_token
from app.utils.password import hash_password

SECRET = "JBSWY3DPEHPK3PXP"
ISSUER = "http://localhost:13000"
RESOURCE = "http://localhost:13000/mcp"
VERIFIER = "v" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
CLAUDE_CODE = "https://claude.ai/oauth/claude-code-client-metadata"


@pytest.fixture
def http():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        db.add(models.Client(id=1, name="Tester", username="tester", password_hash=hash_password("password123"),
                             general_settings={}))
        db.add(models.ClientMfaSetting(client_id=1, enabled=True, totp_secret_encrypted=encrypt_key(SECRET)))
        db.add(models.Client(id=2, name="Other", username="other", password_hash=hash_password("password123"),
                             general_settings={}))
        db.commit()
    app = FastAPI(exception_handlers=main_app.exception_handlers)
    for router in (auth.router, mcp_oauth.router, ai_operations.router):
        app.include_router(router)

    @app.get("/me")
    def me(client: models.Client = Depends(get_current_client)):
        return {"client_id": client.id}

    def override_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = override_db

    def request(method, path, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(run())
    yield request, sessions
    engine.dispose()


def _authorize_body(**overrides):
    body = {
        "username": "tester", "password": "password123", "factor": pyotp.TOTP(SECRET).now(),
        "oauth_client_id": CLAUDE_CODE, "client_name": "Claude Code", "client_source": "cimd",
        "redirect_uri": "http://localhost:45789/callback", "code_challenge": CHALLENGE,
        "scope": "mcp", "resource": RESOURCE, "issuer": ISSUER, "allow_refresh": True,
    }
    return {**body, **overrides}


def _pending(db, *, client_id=1, oauth_client_id=CLAUDE_CODE, allow_refresh=True, now=None, auth_time_ms=None):
    return connections.start_connection(
        db, client_id=client_id, oauth_client_id=oauth_client_id, client_name="Claude Code", client_source="cimd",
        redirect_uri="http://localhost:45789/callback", code_challenge=CHALLENGE, scope="mcp",
        resource=RESOURCE, issuer=ISSUER, allow_refresh=allow_refresh,
        auth_time_ms=auth_time_ms or int(datetime.now(timezone.utc).timestamp() * 1000), now=now,
    )


def _exchange(request, code, **overrides):
    return request("POST", "/auth/mcp/token", json={
        "grant_type": "authorization_code", "client_id": CLAUDE_CODE, "code": code,
        "redirect_uri": "http://localhost:45789/callback", "code_verifier": VERIFIER, **overrides,
    })


def _claims(access_token):
    return jwt.decode(access_token, settings.mcp_jwt_secret, algorithms=[settings.jwt_algorithm],
                      audience=settings.mcp_token_audience)


def bearer(token):
    return {"Authorization": "Bearer " + token}


# ─── Registration ─────────────────────────────────────────

def test_dcr_registration_is_stored_and_checked(http):
    request, sessions = http
    created = request("POST", "/auth/mcp/clients", json={
        "client_name": "Codex", "redirect_uris": ["http://127.0.0.1:5555/callback"],
        "grant_types": ["authorization_code", "refresh_token", "password"],
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["client_id"].startswith("mcp_")
    assert body["grant_types"] == ["authorization_code", "refresh_token"]
    assert abs(body["client_id_issued_at"] - datetime.now(timezone.utc).timestamp()) < 60
    assert request("GET", f"/auth/mcp/clients/{body['client_id']}").json()["redirect_uris"] == [
        "http://127.0.0.1:5555/callback"]
    assert request("GET", "/auth/mcp/clients/mcp_missing").status_code == 404
    # MCP authorization: redirect URIs are loopback or https only.
    for uris in ([], ["http://evil.example/callback"], ["https://claude.ai/cb#x"], ["ftp://x/y"]):
        refused = request("POST", "/auth/mcp/clients", json={"redirect_uris": uris})
        assert refused.status_code == 400 and refused.json() == {"error": "invalid_redirect_uri"}, uris


def test_unused_registrations_expire_and_registrations_are_capped(http, monkeypatch):
    _, sessions = http
    with sessions() as db:
        old = datetime.utcnow() - timedelta(days=31)
        stale = connections.register_client(db, client_name="old", redirect_uris=["http://localhost/cb"],
                                             grant_types=[], now=old).client_id
        used = connections.register_client(db, client_name="used", redirect_uris=["http://localhost/cb"],
                                           grant_types=[], now=old)
        used.last_used_at = datetime.utcnow() - timedelta(days=1)
        used = used.client_id
        db.commit()
        connections.register_client(db, client_name="new", redirect_uris=["http://localhost/cb"], grant_types=[])
        assert connections.get_registered_client(db, stale) is None
        assert connections.get_registered_client(db, used) is not None
        monkeypatch.setattr(connections, "MAX_REGISTERED_CLIENTS", 2)
        with pytest.raises(connections.Refused):
            connections.register_client(db, client_name="x", redirect_uris=["http://localhost/cb"], grant_types=[])


# ─── Authorization ────────────────────────────────────────

def test_authorize_signs_in_with_the_second_factor_and_returns_a_code(http):
    request, sessions = http
    granted = request("POST", "/auth/mcp/authorize", json=_authorize_body())
    assert granted.status_code == 200, granted.text
    assert granted.json()["username"] == "tester"
    with sessions() as db:
        row = db.query(models.McpConnection).one()
        assert row.activated_at is None and row.client_source == "cimd" and row.allow_refresh
        assert row.code_hash and row.code_hash != granted.json()["code"]


@pytest.mark.parametrize("overrides,status,error", [
    ({"password": "wrong"}, 401, "invalid"),
    ({"username": "nobody"}, 401, "invalid"),
    ({"factor": "000000"}, 401, "invalid"),
    ({"code_challenge_method": "plain"}, 400, "invalid_request"),
    ({"issuer": "https://evil.example"}, 400, "invalid_request"),
    ({"client_source": "dcr", "oauth_client_id": "mcp_unknown"}, 400, "invalid_client"),
])
def test_authorize_refusals(http, overrides, status, error):
    request, sessions = http
    refused = request("POST", "/auth/mcp/authorize", json=_authorize_body(**overrides))
    assert (refused.status_code, refused.json()) == (status, {"error": error})
    with sessions() as db:
        assert db.query(models.McpConnection).count() == 0


def test_authorize_refuses_unfinished_or_locked_accounts(http):
    request, sessions = http
    other = request("POST", "/auth/mcp/authorize", json=_authorize_body(username="other"))
    assert (other.status_code, other.json()) == (403, {"error": "setup_required"})
    for _ in range(5):
        request("POST", "/auth/mcp/authorize", json=_authorize_body(password="wrong"))
    locked = request("POST", "/auth/mcp/authorize", json=_authorize_body())
    assert (locked.status_code, locked.json()) == (429, {"error": "locked"})


def test_dcr_client_gets_a_refresh_token_only_if_registered_for_one(http):
    request, sessions = http
    registered = request("POST", "/auth/mcp/clients", json={"redirect_uris": ["http://localhost/callback"]}).json()
    granted = request("POST", "/auth/mcp/authorize", json=_authorize_body(
        oauth_client_id=registered["client_id"], client_source="dcr", allow_refresh=True))
    assert granted.status_code == 200, granted.text
    tokens = _exchange(request, granted.json()["code"], client_id=registered["client_id"]).json()
    assert "refresh_token" not in tokens
    with sessions() as db:
        assert db.query(models.McpOAuthClient).one().last_used_at is not None


# ─── Token ────────────────────────────────────────────────

def test_code_exchange_names_the_connection_and_rotations_keep_the_sign_in_time(http):
    request, sessions = http
    auth_time = int(datetime.now(timezone.utc).timestamp() * 1000) - 60_123
    with sessions() as db:
        code = _pending(db, auth_time_ms=auth_time)
    tokens = _exchange(request, code)
    assert tokens.status_code == 200, tokens.text
    body = tokens.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 3600 and body["scope"] == "mcp"
    claims = _claims(body["access_token"])
    assert claims["aud"] == [RESOURCE, settings.mcp_token_audience] and claims["iss"] == ISSUER
    assert claims["client_id"] == CLAUDE_CODE and claims["username"] == "tester" and claims["backend_client_id"] == 1
    assert claims["auth_time_ms"] == auth_time and isinstance(claims["cid"], int)
    # The code is single use.
    assert _exchange(request, code).json() == {"error": "invalid_grant"}
    for _ in range(3):
        old = body["refresh_token"]
        rotated = request("POST", "/auth/mcp/token", json={
            "grant_type": "refresh_token", "client_id": CLAUDE_CODE, "refresh_token": old})
        assert rotated.status_code == 200, rotated.text
        body = rotated.json()
        assert body["refresh_token"] != old
        assert _claims(body["access_token"])["auth_time_ms"] == auth_time
        assert _claims(body["access_token"])["cid"] == claims["cid"]


@pytest.mark.parametrize("overrides", [
    {"redirect_uri": "http://localhost:1234/callback"},
    {"client_id": "https://evil.example/client"},
    {"code_verifier": "w" * 50},
])
def test_a_mismatched_code_exchange_spends_the_code(http, overrides):
    request, sessions = http
    with sessions() as db:
        code = _pending(db)
    assert _exchange(request, code, **overrides).json() == {"error": "invalid_grant"}
    assert _exchange(request, code).json() == {"error": "invalid_grant"}
    with sessions() as db:
        assert db.query(models.McpConnection).count() == 0


def test_expired_code_is_refused(http):
    _, sessions = http
    with sessions() as db:
        code = _pending(db, now=datetime.utcnow() - timedelta(minutes=6))
        with pytest.raises(connections.InvalidGrant):
            connections.redeem_code(db, code=code, oauth_client_id=CLAUDE_CODE,
                                    redirect_uri="http://localhost:45789/callback", code_verifier=VERIFIER)


def test_refresh_token_replay_ends_the_connection_after_the_grace(http):
    _, sessions = http
    with sessions() as db:
        start = datetime.utcnow()
        connection, first = connections.redeem_code(
            db, code=_pending(db, now=start), oauth_client_id=CLAUDE_CODE,
            redirect_uri="http://localhost:45789/callback", code_verifier=VERIFIER, now=start)
        _, second = connections.refresh(db, refresh_token=first, oauth_client_id=CLAUDE_CODE, now=start)
        # Two refreshes at once: the replaced token still works inside the grace.
        _, third = connections.refresh(db, refresh_token=first, oauth_client_id=CLAUDE_CODE,
                                       now=start + timedelta(seconds=30))
        _, fourth = connections.refresh(db, refresh_token=third, oauth_client_id=CLAUDE_CODE,
                                        now=start + timedelta(seconds=40))
        # After it, the replaced token is a replay: the whole connection ends.
        with pytest.raises(connections.InvalidGrant):
            connections.refresh(db, refresh_token=third, oauth_client_id=CLAUDE_CODE,
                                now=start + timedelta(minutes=5))
        db.refresh(connection)
        assert connection.revoked_reason == "refresh_reuse"
        with pytest.raises(connections.InvalidGrant):
            connections.refresh(db, refresh_token=fourth, oauth_client_id=CLAUDE_CODE,
                                now=start + timedelta(minutes=6))


def test_refresh_token_expires_after_thirty_unused_days(http):
    _, sessions = http
    with sessions() as db:
        start = datetime.utcnow()
        _, token = connections.redeem_code(
            db, code=_pending(db, now=start), oauth_client_id=CLAUDE_CODE,
            redirect_uri="http://localhost:45789/callback", code_verifier=VERIFIER, now=start)
        _, token = connections.refresh(db, refresh_token=token, oauth_client_id=CLAUDE_CODE,
                                       now=start + timedelta(days=29))
        with pytest.raises(connections.InvalidGrant):
            connections.refresh(db, refresh_token=token, oauth_client_id=CLAUDE_CODE,
                                now=start + timedelta(days=60))


def test_password_change_ends_refreshes_and_marks_the_connection(http):
    request, sessions = http
    with sessions() as db:
        code = _pending(db, auth_time_ms=int(datetime.now(timezone.utc).timestamp() * 1000) - 5000)
    body = _exchange(request, code).json()
    with sessions() as db:
        db.get(models.Client, 1).tokens_valid_after = datetime.utcnow()
        db.commit()
    refused = request("POST", "/auth/mcp/token", json={
        "grant_type": "refresh_token", "client_id": CLAUDE_CODE, "refresh_token": body["refresh_token"]})
    assert refused.json() == {"error": "invalid_grant"}
    ui = create_typed_token(user_id=1, username="Tester", token_type="access")
    listed = request("GET", "/ai/mcp/connections", headers=bearer(ui)).json()
    assert [row["status"] for row in listed["connections"]] == ["reconnect_required"]


# ─── Ending a connection ──────────────────────────────────

def test_the_person_sees_and_ends_a_connection_and_its_tokens_stop(http):
    request, sessions = http
    with sessions() as db:
        code = _pending(db)
    body = _exchange(request, code).json()
    exchanged = request("POST", "/auth/mcp/exchange", json={"mcp_access_token": body["access_token"]})
    assert exchanged.status_code == 200, exchanged.text
    backend_token = exchanged.json()["access_token"]
    assert request("GET", "/me", headers=bearer(backend_token)).status_code == 200

    ui = create_typed_token(user_id=1, username="Tester", token_type="access")
    listed = request("GET", "/ai/mcp/connections", headers=bearer(ui))
    assert listed.status_code == 200, listed.text
    assert listed.json()["mcp_url"].endswith("/mcp")
    [row] = listed.json()["connections"]
    assert row["client_name"] == "Claude Code" and row["client_host"] == "claude.ai"
    assert row["redirect_host"] == "localhost" and row["status"] == "active" and row["refreshable"]
    other = create_typed_token(user_id=2, username="Other", token_type="access")
    assert request("GET", "/ai/mcp/connections", headers=bearer(other)).json()["connections"] == []
    assert request("DELETE", f"/ai/mcp/connections/{row['id']}", headers=bearer(other)).status_code == 404

    assert request("DELETE", f"/ai/mcp/connections/{row['id']}", headers=bearer(ui)).status_code == 204
    # The exchanged token stops at the next request, the MCP token at the next exchange,
    # and the refresh token at the next refresh.
    stopped = request("GET", "/me", headers=bearer(backend_token))
    assert stopped.status_code == 401
    assert request("POST", "/auth/mcp/exchange", json={"mcp_access_token": body["access_token"]}).status_code == 401
    assert request("POST", "/auth/mcp/token", json={
        "grant_type": "refresh_token", "client_id": CLAUDE_CODE, "refresh_token": body["refresh_token"],
    }).json() == {"error": "invalid_grant"}
    assert request("GET", "/ai/mcp/connections", headers=bearer(ui)).json()["connections"] == []
    assert request("DELETE", f"/ai/mcp/connections/{row['id']}", headers=bearer(ui)).status_code == 404


def test_backend_tokens_from_before_connections_are_refused(http):
    request, _ = http
    legacy = create_typed_token(user_id=1, username="Tester", token_type="access",
                                extra_claims={"chn": "mcp", "mcp_client_id": "mcp_old"})
    assert request("GET", "/me", headers=bearer(legacy)).status_code == 401


def test_the_ai_cannot_see_or_end_connections():
    for method in ("GET", "DELETE"):
        assert ai_policy_service.mcp_refusal(None, 1, method, "/ai/mcp/connections") == "ai_connections"
    assert ai_policy_service.mcp_refusal(None, 1, "DELETE", "/ai/mcp/connections/3") == "ai_connections"
