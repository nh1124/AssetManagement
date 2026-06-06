from __future__ import annotations

import pytest
import pyotp
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.routers import auth
from backend.app.utils.jwt import decode_token
from backend.app.utils.password import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db):
    client = models.Client(
        id=1,
        name="Test User",
        username="tester",
        password_hash=hash_password("password123"),
        ai_config={},
        general_settings={},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def test_login_without_mfa_returns_access_token() -> None:
    db = _session()
    try:
        _client(db)

        result = auth.login(auth.LoginRequest(username="tester", password="password123"), db)

        assert result["mfa_required"] is False
        assert result["access_token"]
        assert decode_token(result["access_token"])["type"] == "access"
    finally:
        db.close()


def test_mfa_login_requires_totp_then_returns_access_token() -> None:
    db = _session()
    try:
        client = _client(db)
        setup = auth.start_mfa_setup(auth.MfaStartRequest(current_password="password123"), db, client)
        code = pyotp.TOTP(setup["manual_entry_key"]).now()
        enabled = auth.verify_mfa_setup(auth.MfaSetupVerifyRequest(code=code), db, client)

        first_step = auth.login(auth.LoginRequest(username="tester", password="password123"), db)

        assert first_step["mfa_required"] is True
        assert first_step["access_token"] is None
        assert decode_token(first_step["mfa_token"])["type"] == "mfa"
        assert len(enabled["recovery_codes"]) == 8

        second_code = pyotp.TOTP(setup["manual_entry_key"]).now()
        completed = auth.verify_mfa_login(
            auth.MfaLoginVerifyRequest(mfa_token=first_step["mfa_token"], code=second_code),
            db,
        )

        assert completed["mfa_required"] is False
        assert decode_token(completed["access_token"])["type"] == "access"
    finally:
        db.close()


def test_recovery_code_can_be_used_only_once() -> None:
    db = _session()
    try:
        client = _client(db)
        setup = auth.start_mfa_setup(auth.MfaStartRequest(current_password="password123"), db, client)
        code = pyotp.TOTP(setup["manual_entry_key"]).now()
        enabled = auth.verify_mfa_setup(auth.MfaSetupVerifyRequest(code=code), db, client)
        recovery_code = enabled["recovery_codes"][0]

        first_step = auth.login(auth.LoginRequest(username="tester", password="password123"), db)
        completed = auth.verify_mfa_login(
            auth.MfaLoginVerifyRequest(mfa_token=first_step["mfa_token"], recovery_code=recovery_code),
            db,
        )
        assert completed["access_token"]

        second_step = auth.login(auth.LoginRequest(username="tester", password="password123"), db)
        with pytest.raises(HTTPException) as exc:
            auth.verify_mfa_login(
                auth.MfaLoginVerifyRequest(mfa_token=second_step["mfa_token"], recovery_code=recovery_code),
                db,
            )

        assert exc.value.status_code == 401
    finally:
        db.close()


def test_disable_mfa_requires_reauthentication() -> None:
    db = _session()
    try:
        client = _client(db)
        setup = auth.start_mfa_setup(auth.MfaStartRequest(current_password="password123"), db, client)
        code = pyotp.TOTP(setup["manual_entry_key"]).now()
        auth.verify_mfa_setup(auth.MfaSetupVerifyRequest(code=code), db, client)

        with pytest.raises(HTTPException) as exc:
            auth.disable_mfa(auth.MfaFactorRequest(current_password="wrong-password"), db, client)
        assert exc.value.status_code == 401

        auth.disable_mfa(auth.MfaFactorRequest(current_password="password123"), db, client)
        status = auth.get_mfa_status(db, client)
        assert status["enabled"] is False
        assert status["recovery_codes_remaining"] == 0
    finally:
        db.close()
