from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.config import settings
from backend.app.database import Base
from backend.app.routers import auth
from backend.app.utils.jwt import decode_token
from backend.app.utils.password import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db, client_id: int, username: str):
    client = models.Client(
        id=client_id,
        name=f"User {client_id}",
        username=username,
        password_hash=hash_password("password123"),
        ai_config={},
        general_settings={},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def _mcp_token(*, username: str, backend_client_id: int, issuer: str = "http://localhost:13000") -> str:
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
            "exp": now + timedelta(minutes=5),
        },
        settings.mcp_jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def test_mcp_token_exchange_issues_backend_token_for_subject() -> None:
    db = _session()
    try:
        client = _client(db, 1, "alice")
        token = _mcp_token(username="alice", backend_client_id=client.id)

        result = auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)
        payload = decode_token(result["access_token"])

        assert result["client_id"] == client.id
        assert result["username"] == "alice"
        assert result["mcp_client_id"] == "mcp_test_client"
        assert payload["sub"] == str(client.id)
        assert payload["type"] == "access"
    finally:
        db.close()


def test_mcp_token_exchange_accepts_local_https_issuer_variant() -> None:
    db = _session()
    try:
        client = _client(db, 1, "alice")
        token = _mcp_token(username="alice", backend_client_id=client.id, issuer="https://localhost:13000")

        result = auth.exchange_mcp_token(auth.McpTokenExchangeRequest(mcp_access_token=token), db)

        assert result["client_id"] == client.id
        assert result["username"] == "alice"
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
