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


def _mfa_change_request(db, client):
    row = models.AiChangeRequest(
        client_id=client.id, source="mcp", resource="data_transfer", action="import", risk="critical",
        idempotency_key="wp8-mfa", requires_mfa=True,
    )
    db.add(row)
    db.commit()
    return row


def test_step_up_refuses_password_and_requires_mfa_setup() -> None:
    from backend.app.domain.errors import Refused
    from backend.app.workflows.ai_change_request_workflow import approve_change_request

    db = _session()
    try:
        client = _client(db)
        with pytest.raises(HTTPException) as no_mfa:
            auth.reauth(auth.MfaFactorRequest(current_password="password123"), db, client)
        assert no_mfa.value.status_code == 403

        # A step-up token alone does not approve while MFA is off.
        token = decode_token(auth._issue_step_up_token(client)["step_up_token"])
        row = _mfa_change_request(db, client)
        with pytest.raises(Refused, match="MFA setup required"):
            approve_change_request(db, client.id, client.id, row.id, token)

        setup = auth.start_mfa_setup(auth.MfaStartRequest(current_password="password123"), db, client)
        enabled = auth.verify_mfa_setup(
            auth.MfaSetupVerifyRequest(code=pyotp.TOTP(setup["manual_entry_key"]).now()), db, client,
        )
        with pytest.raises(HTTPException) as password_only:
            auth.reauth(auth.MfaFactorRequest(current_password="password123"), db, client)
        assert password_only.value.status_code == 401

        step = auth.reauth(auth.MfaFactorRequest(recovery_code=enabled["recovery_codes"][0]), db, client)
        approved = approve_change_request(db, client.id, client.id, row.id, decode_token(step["step_up_token"]))
        assert approved.status == "approved"
    finally:
        db.close()
