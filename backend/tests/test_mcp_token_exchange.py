from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.config import settings
from backend.app.database import Base
from backend.app.routers import auth
from backend.app.security import encrypt_key
from backend.app.utils.jwt import decode_token
from backend.app.utils.password import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db, client_id: int, username: str, *, mfa_enabled: bool | None = True):
    client = models.Client(
        id=client_id,
        name=f"User {client_id}",
        username=username,
        password_hash=hash_password("password123"),
        general_settings={},
    )
    db.add(client)
    if mfa_enabled is not None:
        db.add(models.ClientMfaSetting(
            client_id=client_id, enabled=mfa_enabled,
            totp_secret_encrypted=encrypt_key("JBSWY3DPEHPK3PXP"),
        ))
    db.commit()
    db.refresh(client)
    return client


def _connect(db, client_id: int, *, oauth_client_id: str = "mcp_test_client", connection_id: int | None = None) -> int:
    """An active connection, as /auth/mcp/token leaves one (WP35)."""
    now = datetime.utcnow()
    connection = models.McpConnection(
        id=connection_id, client_id=client_id, oauth_client_id=oauth_client_id, client_source="dcr",
        redirect_uri="http://localhost/callback", scope="mcp", resource="http://localhost:13000/mcp",
        issuer="http://localhost:13000", auth_time_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        allow_refresh=False, created_at=now, activated_at=now, expires_at=now + timedelta(hours=1),
    )
    db.add(connection)
    db.commit()
    return connection.id


def _mcp_token(*, username: str, backend_client_id: int, issuer: str = "http://localhost:13000", auth_time_ms="now",
               cid: int | None = None) -> str:
    now = datetime.utcnow()
    return jwt.encode(
        {
            "sub": username,
            "username": username,
            "backend_client_id": backend_client_id,
            "client_id": "mcp_test_client",
            "scope": "mcp",
            "type": "access",
            "aud": ["http://localhost:13000/mcp", settings.mcp_token_audience],
            "iss": issuer,
            "iat": now,
            **({} if auth_time_ms is None else {"auth_time_ms": datetime.now(timezone.utc).timestamp() * 1000 if auth_time_ms == "now" else auth_time_ms}),
            "exp": now + timedelta(minutes=5),
            **({} if cid is None else {"cid": cid}),
        },
        settings.mcp_jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def test_mcp_token_exchange_issues_backend_token_for_subject() -> None:
    db = _session()
    try:
        client = _client(db, 1, "alice")
        cid = _connect(db, client.id)
        token = _mcp_token(username="alice", backend_client_id=client.id, cid=cid)

        result = auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)
        payload = decode_token(result["access_token"])

        assert result["client_id"] == client.id
        assert result["username"] == "alice"
        assert result["mcp_client_id"] == "mcp_test_client"
        assert payload["sub"] == str(client.id)
        assert payload["type"] == "access"
        assert isinstance(payload["iat_ms"], (int, float))
        assert payload["chn"] == "mcp" and payload["cid"] == cid
        assert db.get(models.McpConnection, cid).last_used_at is not None
    finally:
        db.close()


def test_mcp_token_exchange_accepts_local_https_issuer_variant() -> None:
    db = _session()
    try:
        client = _client(db, 1, "alice")
        token = _mcp_token(username="alice", backend_client_id=client.id, issuer="https://localhost:13000",
                           cid=_connect(db, client.id))

        result = auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)

        assert result["client_id"] == client.id
        assert result["username"] == "alice"
    finally:
        db.close()


@pytest.mark.parametrize("mfa_enabled", [None, False])
def test_mcp_token_exchange_requires_enabled_mfa(mfa_enabled) -> None:
    db = _session()
    try:
        client = _client(db, 1, "alice", mfa_enabled=mfa_enabled)
        token = _mcp_token(username="alice", backend_client_id=client.id)

        with pytest.raises(HTTPException) as error:
            auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)

        assert error.value.status_code == 401
        assert error.value.detail == "MFA setup required"
        assert error.value.detail.in_language("ja") == "先にアプリで認証アプリを設定してください。"
    finally:
        db.close()


def test_mcp_token_exchange_rejects_wrong_subject_or_issuer() -> None:
    db = _session()
    try:
        _client(db, 1, "alice")
        _client(db, 2, "bob")

        wrong_subject = _mcp_token(username="alice", backend_client_id=2)
        with pytest.raises(HTTPException) as subject_exc:
            auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=wrong_subject), db)
        assert subject_exc.value.status_code == 401

        wrong_issuer = _mcp_token(username="alice", backend_client_id=1, issuer="https://evil.example")
        with pytest.raises(HTTPException) as issuer_exc:
            auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=wrong_issuer), db)
        assert issuer_exc.value.status_code == 401
    finally:
        db.close()


@pytest.mark.parametrize("auth_time", [None, "invalid", True, float("inf"), float("nan"), 100])
def test_exchange_rejects_missing_malformed_or_revoked_authorization(auth_time):
    db = _session()
    try:
        client = _client(db, 1, "alice")
        client.tokens_valid_after = datetime.utcnow()
        db.commit()
        token = _mcp_token(username="alice", backend_client_id=1, auth_time_ms=auth_time)
        with pytest.raises(HTTPException) as error:
            auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)
        assert error.value.status_code == 401
    finally:
        db.close()


def test_exchange_requires_auth_time_even_without_cutoff():
    db = _session()
    try:
        _client(db, 1, "alice")
        token = _mcp_token(username="alice", backend_client_id=1, auth_time_ms=None)
        with pytest.raises(HTTPException) as error:
            auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)
        assert error.value.status_code == 401
    finally:
        db.close()


def test_exchange_revocation_compares_original_authorization_in_milliseconds():
    db = _session()
    try:
        client = _client(db, 1, "alice")
        cutoff = datetime(2026, 10, 22, 12, 0, 0, 900000)
        client.tokens_valid_after = cutoff
        db.commit()
        cutoff_ms = cutoff.replace(tzinfo=timezone.utc).timestamp() * 1000
        # Fresh JWT iat cannot override an authorization made before revocation.
        old = _mcp_token(username="alice", backend_client_id=1, auth_time_ms=cutoff_ms - 800)
        with pytest.raises(HTTPException) as error:
            auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=old), db)
        assert error.value.status_code == 401
        current = _mcp_token(username="alice", backend_client_id=1, auth_time_ms=cutoff_ms, cid=_connect(db, 1))
        result = auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=current), db)
        assert decode_token(result["access_token"])["iat_ms"]
    finally:
        db.close()


def test_exchange_requires_a_standing_connection_of_the_same_app_and_person():
    """WP35: a token without cid, or naming an ended or foreign connection, is refused."""
    db = _session()
    try:
        alice = _client(db, 1, "alice")
        _client(db, 2, "bob")
        refused = [
            _mcp_token(username="alice", backend_client_id=1),
            _mcp_token(username="alice", backend_client_id=1, cid=999),
            _mcp_token(username="alice", backend_client_id=1, cid=_connect(db, 2)),
            _mcp_token(username="alice", backend_client_id=1, cid=_connect(db, 1, oauth_client_id="mcp_other")),
        ]
        ended = _connect(db, alice.id)
        connection = db.get(models.McpConnection, ended)
        connection.revoked_at = datetime.utcnow()
        db.commit()
        refused.append(_mcp_token(username="alice", backend_client_id=1, cid=ended))
        for token in refused:
            with pytest.raises(HTTPException) as error:
                auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)
            assert error.value.status_code == 401
    finally:
        db.close()
