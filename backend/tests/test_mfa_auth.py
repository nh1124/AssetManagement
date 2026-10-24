"""Mandatory TOTP, staged sign-in, factor replacement and account lockout."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pyotp
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import Base
from app.dependencies import get_current_client
from app.routers import auth
from app.security import decrypt_key
from app.services import client_service, mfa_service
from app.utils.jwt import create_access_token, create_typed_token, decode_token
from app.utils.password import hash_password, verify_password


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add(models.Client(id=1, name="Test User", username="tester",
                                  password_hash=hash_password("password123"), general_settings={}))
        session.commit()
        yield session
    engine.dispose()


def login(db, password="password123", username="tester"):
    return auth.login(auth.LoginRequest(username=username, password=password), db)


def enroll(db, at=None):
    step = login(db)
    setup = auth.start_enrollment(auth.StepRequest(step_token=step["step_token"]), db)
    totp = pyotp.TOTP(setup["manual_entry_key"])
    completed = auth.verify_enrollment(auth.EnrollVerifyRequest(
        step_token=step["step_token"], code=totp.at(at) if at else totp.now()), db)
    return setup["manual_entry_key"], completed


def resolve(db, token):
    return asyncio.run(get_current_client(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db))


def older_token(client, seconds=30):
    payload = decode_token(create_access_token(client.id, client.name))
    payload["iat"] -= seconds
    payload["iat_ms"] -= seconds * 1000
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_first_login_enroll_then_mfa_sign_in(db):
    step = login(db)
    assert step["access_token"] is None
    assert step["token_type"] == "step"
    assert step["next_step"] == "mfa_setup"
    assert "mfa_required" not in step and "mfa_token" not in step
    payload = decode_token(step["step_token"])
    assert payload["type"] == "mfa_setup"
    assert payload["exp"] - payload["iat"] == 600
    secret, completed = enroll(db)
    assert len(completed["recovery_codes"]) == 8
    assert resolve(db, completed["access_token"]).id == 1
    step = login(db)
    assert step["next_step"] == "mfa" and step["token_type"] == "step"
    assert step["mfa_required"] is True and step["mfa_token"] == step["step_token"]
    payload = decode_token(step["mfa_token"])
    assert payload["type"] == "mfa" and payload["exp"] - payload["iat"] == 300
    completed = auth.verify_mfa_login(auth.MfaLoginVerifyRequest(
        mfa_token=step["mfa_token"], recovery_code=completed["recovery_codes"][0]), db)
    assert resolve(db, completed["access_token"]).id == 1


def test_enroll_start_replaces_unconfirmed_secret_and_completed_step_is_rejected(db):
    step = login(db)["step_token"]
    first = auth.start_enrollment(auth.StepRequest(step_token=step), db)
    second = auth.start_enrollment(auth.StepRequest(step_token=step), db)
    assert first["manual_entry_key"] != second["manual_entry_key"]
    assert decrypt_key(db.query(models.ClientMfaSetting).one().totp_secret_encrypted) == second["manual_entry_key"]
    auth.verify_enrollment(auth.EnrollVerifyRequest(
        step_token=step, code=pyotp.TOTP(second["manual_entry_key"]).now()), db)
    for call in (
        lambda: auth.start_enrollment(auth.StepRequest(step_token=step), db),
        lambda: auth.verify_enrollment(auth.EnrollVerifyRequest(step_token=step, code="bad"), db),
    ):
        with pytest.raises(HTTPException) as error:
            call()
        assert error.value.status_code == 401
    assert mfa_service.mfa_enabled(db, 1)


@pytest.mark.parametrize("enabled", [False, True])
def test_required_password_change_precedes_mfa_and_revokes_access(db, enabled):
    if enabled:
        enroll(db)
    client = db.get(models.Client, 1)
    old = older_token(client)
    client.must_change_password = True
    db.commit()
    step = login(db)
    assert step["next_step"] == "password_change"
    payload = decode_token(step["step_token"])
    assert payload["type"] == "password_change" and payload["exp"] - payload["iat"] == 600
    for password in ("short", "password123"):
        with pytest.raises(HTTPException) as error:
            auth.change_password(auth.PasswordChangeRequest(step_token=step["step_token"], new_password=password), db)
        assert error.value.status_code == 400
    following = auth.change_password(auth.PasswordChangeRequest(
        step_token=step["step_token"], new_password="newpassword123"), db)
    assert following["next_step"] == ("mfa" if enabled else "mfa_setup")
    assert following["access_token"] is None
    assert not client.must_change_password and client.tokens_valid_after
    assert verify_password("newpassword123", client.password_hash)
    with pytest.raises(HTTPException) as error:
        resolve(db, old)
    assert error.value.status_code == 401
    assert login(db, password="newpassword123")["next_step"] == following["next_step"]
    with pytest.raises(HTTPException) as error:
        auth.change_password(auth.PasswordChangeRequest(step_token=step["step_token"], new_password="anotherpassword"), db)
    assert error.value.status_code == 401


STEPS = ["password_change", "mfa_setup", "mfa", "access", "step_up"]


@pytest.mark.parametrize("endpoint,token_type", [
    (endpoint, kind)
    for endpoint, expected in (("password", "password_change"), ("start", "mfa_setup"), ("enroll", "mfa_setup"), ("mfa", "mfa"))
    for kind in STEPS if kind != expected
])
def test_step_endpoints_reject_wrong_token_types(db, endpoint, token_type):
    token = create_typed_token(1, "Test User", token_type)
    calls = {
        "password": lambda: auth.change_password(auth.PasswordChangeRequest(step_token=token, new_password="newpassword"), db),
        "start": lambda: auth.start_enrollment(auth.StepRequest(step_token=token), db),
        "enroll": lambda: auth.verify_enrollment(auth.EnrollVerifyRequest(step_token=token, code="bad"), db),
        "mfa": lambda: auth.verify_mfa_login(auth.MfaLoginVerifyRequest(mfa_token=token, code="bad"), db),
    }
    with pytest.raises(HTTPException) as error:
        calls[endpoint]()
    assert error.value.status_code == 401
    assert db.get(models.Client, 1).failed_login_count == 0


@pytest.mark.parametrize("token_type", ["password_change", "mfa_setup", "mfa", "step_up"])
def test_step_tokens_cannot_authenticate_an_ordinary_request(db, token_type):
    with pytest.raises(HTTPException) as error:
        resolve(db, create_typed_token(1, "Test User", token_type))
    assert error.value.status_code == 401


def test_register_returns_enrollment_without_access(db):
    result = auth.register(auth.RegisterRequest(username="new", password="password123"), db)
    assert result["next_step"] == "mfa_setup" and result["access_token"] is None
    assert decode_token(result["step_token"])["sub"] == str(result["client_id"])


def test_recovery_code_can_be_used_only_once(db):
    _, completed = enroll(db)
    recovery_code = completed["recovery_codes"][0]
    step = login(db)
    result = auth.verify_mfa_login(auth.MfaLoginVerifyRequest(mfa_token=step["mfa_token"], recovery_code=recovery_code), db)
    assert resolve(db, result["access_token"]).id == 1
    with pytest.raises(HTTPException) as error:
        auth.verify_mfa_login(auth.MfaLoginVerifyRequest(mfa_token=step["mfa_token"], recovery_code=recovery_code), db)
    assert error.value.status_code == 401
    assert db.get(models.Client, 1).failed_login_count == 1


@pytest.mark.parametrize("use_recovery", [False, True])
def test_replacement_preserves_old_factor_until_verified_and_revokes_tokens(db, use_recovery, monkeypatch):
    # Pin the clock from enrollment on: across a TOTP step boundary after enrollment
    # the old code below would legitimately be new and inside the verification window.
    now = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
    verification_time = now + timedelta(seconds=30)
    clock = [now]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0] if tz else clock[0].replace(tzinfo=None)
        @classmethod
        def utcnow(cls):
            return clock[0].replace(tzinfo=None)
    monkeypatch.setattr(mfa_service, "datetime", Clock)
    old_secret, completed = enroll(db, at=now)
    clock[0] = verification_time
    client = db.get(models.Client, 1)
    old_token = older_token(client)
    # Make the old/new code sets distinct across the test's verification window.
    old_codes = {pyotp.TOTP(old_secret).at(now, counter_offset=offset) for offset in range(-2, 3)}
    candidate = pyotp.random_base32()
    while old_codes & {pyotp.TOTP(candidate).at(now, counter_offset=offset) for offset in range(-2, 3)}:
        candidate = pyotp.random_base32()
    monkeypatch.setattr(mfa_service.pyotp, "random_base32", lambda: candidate)
    proof = (auth.MfaFactorRequest(recovery_code=completed["recovery_codes"][0]) if use_recovery
             else auth.MfaFactorRequest(code=pyotp.TOTP(old_secret).at(verification_time)))
    setup = auth.start_mfa_replacement(proof, db, client)
    assert setup["manual_entry_key"] != old_secret
    setting = mfa_service.get_mfa_setting(db, client)
    assert setting.pending_totp_secret_encrypted and decrypt_key(setting.totp_secret_encrypted) == old_secret
    assert not mfa_service.verify_mfa_factor(db, client, code=pyotp.TOTP(old_secret).at(now))
    assert mfa_service.verify_mfa_factor(db, client, recovery_code=completed["recovery_codes"][2])
    assert not mfa_service.verify_mfa_factor(db, client, code="invalid")
    with pytest.raises(HTTPException) as replay:
        auth.verify_mfa_replacement(auth.MfaSetupVerifyRequest(
            code=pyotp.TOTP(setup["manual_entry_key"]).generate_otp(setting.last_totp_step)), db, client)
    assert replay.value.status_code == 401
    new_code = pyotp.TOTP(setup["manual_entry_key"]).at(verification_time, counter_offset=1)
    replaced = auth.verify_mfa_replacement(auth.MfaSetupVerifyRequest(code=new_code), db, client)
    assert setting.pending_totp_secret_encrypted is None
    assert decrypt_key(setting.totp_secret_encrypted) == setup["manual_entry_key"]
    assert not mfa_service.verify_mfa_factor(db, client, code=new_code)
    assert not mfa_service.verify_totp_code(setting, pyotp.TOTP(old_secret).at(verification_time))
    assert set(replaced["recovery_codes"]).isdisjoint(completed["recovery_codes"])
    assert not mfa_service.verify_mfa_factor(db, client, recovery_code=completed["recovery_codes"][1])
    with pytest.raises(HTTPException) as error:
        resolve(db, old_token)
    assert error.value.status_code == 401
    assert resolve(db, replaced["access_token"]).id == 1


def test_five_password_failures_lock_account_even_for_correct_password(db):
    for attempt in range(1, 6):
        with pytest.raises(HTTPException) as error:
            login(db, password="wrong")
        assert error.value.status_code == (429 if attempt == 5 else 401)
    client = db.get(models.Client, 1)
    assert client.failed_login_count == 5
    assert datetime.utcnow() + timedelta(minutes=14) < client.locked_until <= datetime.utcnow() + timedelta(minutes=15)
    with pytest.raises(HTTPException) as error:
        login(db)
    assert error.value.status_code == 429 and error.value.detail == auth.LOCKED
    assert client.failed_login_count == 5
    client.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    login(db)
    assert client.failed_login_count == 5 and client.locked_until is not None


def test_success_resets_failures_and_unknown_user_does_not_count(db):
    for _ in range(2):
        with pytest.raises(HTTPException):
            login(db, password="wrong")
    client = db.get(models.Client, 1)
    assert client.failed_login_count == 2
    for _ in range(6):
        with pytest.raises(HTTPException) as error:
            login(db, username="missing")
        assert error.value.status_code == 401
    assert client.failed_login_count == 2
    login(db)
    assert client.failed_login_count == 2
    enroll(db)
    assert client.failed_login_count == 0
    client.failed_login_count = 5
    client.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException):
        login(db, password="wrong")
    assert client.failed_login_count == 1 and client.locked_until is None


@pytest.mark.parametrize("endpoint", ["enroll", "mfa", "replace_start", "replace_verify", "reauth"])
def test_wrong_factor_counts_and_locked_endpoints_refuse_valid_factor(db, endpoint):
    if endpoint == "enroll":
        step = login(db)
        setup = auth.start_enrollment(auth.StepRequest(step_token=step["step_token"]), db)
        secret = setup["manual_entry_key"]
    else:
        secret, completed = enroll(db)
        step = login(db)
    client = db.get(models.Client, 1)
    if endpoint == "replace_verify":
        setup = auth.start_mfa_replacement(auth.MfaFactorRequest(recovery_code=completed["recovery_codes"][0]), db, client)
        secret = setup["manual_entry_key"]
    def call(code):
        if endpoint == "enroll":
            return auth.verify_enrollment(auth.EnrollVerifyRequest(step_token=step["step_token"], code=code), db)
        if endpoint == "mfa":
            return auth.verify_mfa_login(auth.MfaLoginVerifyRequest(mfa_token=step["mfa_token"], code=code), db)
        if endpoint == "replace_start":
            return auth.start_mfa_replacement(auth.MfaFactorRequest(code=code), db, client)
        if endpoint == "replace_verify":
            return auth.verify_mfa_replacement(auth.MfaSetupVerifyRequest(code=code), db, client)
        return auth.reauth(auth.MfaFactorRequest(code=code), db, client)
    for attempt in range(1, 6):
        with pytest.raises(HTTPException) as error:
            call("invalid")
        assert client.failed_login_count == attempt
        assert error.value.status_code == (429 if attempt == 5 else 400 if endpoint == "enroll" else 401)
    with pytest.raises(HTTPException) as error:
        call(pyotp.TOTP(secret).now())
    assert error.value.status_code == 429
    client.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    call(pyotp.TOTP(secret).at(datetime.now(timezone.utc), counter_offset=1))
    if endpoint == "replace_start":
        assert client.failed_login_count == 5  # No completed authentication yet.
    else:
        assert client.failed_login_count == 0 and client.locked_until is None


def test_recovery_regeneration_requires_factor_and_returns_new_codes(db):
    _, completed = enroll(db)
    client = db.get(models.Client, 1)
    with pytest.raises(HTTPException) as error:
        auth.regenerate_recovery_codes(auth.MfaFactorRequest(current_password="password123"), db, client)
    assert error.value.status_code == 401
    new = auth.regenerate_recovery_codes(auth.MfaFactorRequest(recovery_code=completed["recovery_codes"][0]), db, client)
    assert len(new["recovery_codes"]) == 8
    assert set(new["recovery_codes"]).isdisjoint(completed["recovery_codes"])


def test_revocation_uses_milliseconds_and_profile_password_returns_working_token(db):
    client = db.get(models.Client, 1)
    payload = decode_token(create_access_token(client.id, client.name))
    second = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    payload["iat_ms"] = second.timestamp() * 1000 + 100
    payload["exp"] += 86400
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    client.tokens_valid_after = second.replace(tzinfo=None, microsecond=900000)
    db.commit()
    with pytest.raises(HTTPException) as error:
        resolve(db, token)
    assert error.value.status_code == 401
    payload["iat_ms"] = second.timestamp() * 1000 + 900
    assert resolve(db, jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)).id == 1
    result = auth.update_profile(auth.ProfileUpdate(password="changedpassword", current_password="password123"), db, client)
    assert result["message"] == "Profile updated successfully"
    assert resolve(db, result["access_token"]).id == 1
    assert client.tokens_valid_after.microsecond != 0


def test_step_up_refuses_password_and_requires_mfa_setup(db):
    from app.domain.errors import Refused
    from app.workflows.ai_change_request_workflow import approve_change_request

    client = db.get(models.Client, 1)
    with pytest.raises(HTTPException) as no_mfa:
        auth.reauth(auth.MfaFactorRequest(current_password="password123"), db, client)
    assert no_mfa.value.status_code == 403
    row = models.AiChangeRequest(client_id=1, source="mcp", resource="data_transfer", action="import",
                                 risk="critical", idempotency_key="wp31-mfa", requires_mfa=True)
    db.add(row)
    db.commit()
    token = decode_token(auth._issue_step_up_token(client)["step_up_token"])
    with pytest.raises(Refused, match="MFA setup required"):
        approve_change_request(db, 1, 1, row.id, token)
    _, enabled = enroll(db)
    with pytest.raises(HTTPException) as password_only:
        auth.reauth(auth.MfaFactorRequest(current_password="password123"), db, client)
    assert password_only.value.status_code == 401
    step = auth.reauth(auth.MfaFactorRequest(recovery_code=enabled["recovery_codes"][0]), db, client)
    approved = approve_change_request(db, 1, 1, row.id, decode_token(step["step_up_token"]))
    assert approved.status == "approved"


@pytest.mark.parametrize("endpoint,kind", [
    ("password", "password_change"), ("start", "mfa_setup"), ("enroll", "mfa_setup"), ("mfa", "mfa"),
])
def test_expired_step_tokens_are_rejected(db, endpoint, kind):
    token = create_typed_token(1, "Test User", kind, expires_delta=timedelta(minutes=-1))
    calls = {
        "password": lambda: auth.change_password(auth.PasswordChangeRequest(step_token=token, new_password="newpassword"), db),
        "start": lambda: auth.start_enrollment(auth.StepRequest(step_token=token), db),
        "enroll": lambda: auth.verify_enrollment(auth.EnrollVerifyRequest(step_token=token, code="bad"), db),
        "mfa": lambda: auth.verify_mfa_login(auth.MfaLoginVerifyRequest(mfa_token=token, code="bad"), db),
    }
    with pytest.raises(HTTPException) as error:
        calls[endpoint]()
    assert error.value.status_code == 401


def test_revocation_rejects_access_token_without_millisecond_issued_at(db):
    client = db.get(models.Client, 1)
    payload = decode_token(create_access_token(client.id, client.name))
    payload.pop("iat_ms")
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    client.tokens_valid_after = datetime.utcnow()
    db.commit()
    with pytest.raises(HTTPException) as error:
        resolve(db, token)
    assert error.value.status_code == 401


def test_alternating_correct_password_and_wrong_mfa_locks_account(db):
    enroll(db)
    for attempt in range(1, 6):
        step = login(db)
        with pytest.raises(HTTPException) as error:
            auth.verify_mfa_login(auth.MfaLoginVerifyRequest(mfa_token=step["mfa_token"], code="invalid"), db)
        assert error.value.status_code == (429 if attempt == 5 else 401)
        assert db.get(models.Client, 1).failed_login_count == attempt
    with pytest.raises(HTTPException) as error:
        login(db)
    assert error.value.status_code == 429


def test_partial_enrollment_and_required_password_change_do_not_reset_failures(db):
    client = db.get(models.Client, 1)
    client.failed_login_count = 3
    client.must_change_password = True
    db.commit()
    step = login(db)
    following = auth.change_password(auth.PasswordChangeRequest(
        step_token=step["step_token"], new_password="newpassword123"), db)
    assert client.failed_login_count == 3
    setup = auth.start_enrollment(auth.StepRequest(step_token=following["step_token"]), db)
    assert client.failed_login_count == 3
    auth.verify_enrollment(auth.EnrollVerifyRequest(
        step_token=following["step_token"], code=pyotp.TOTP(setup["manual_entry_key"]).now()), db)
    assert client.failed_login_count == 0


def test_success_cannot_clear_a_concurrently_set_lock(db):
    client = db.get(models.Client, 1)
    client.failed_login_count = 4
    db.commit()
    with Session(db.get_bind(), expire_on_commit=False) as stale_session:
        stale_client = stale_session.get(models.Client, 1)
        assert stale_client.locked_until is None
        client_service.record_auth_failure(db, client)
        client_service.record_auth_success(stale_session, stale_client)
        assert stale_client.failed_login_count == 5
        assert client_service.is_locked(stale_client)
    db.refresh(client)
    assert client.failed_login_count == 5 and client_service.is_locked(client)


@pytest.mark.parametrize("fields", [{"password": "changedpassword"}, {"email": "changed@example.com"}])
def test_profile_wrong_current_password_locks_and_refuses_correct_password(db, fields):
    client = db.get(models.Client, 1)
    original_hash = client.password_hash
    for attempt in range(1, 6):
        with pytest.raises(HTTPException) as error:
            auth.update_profile(auth.ProfileUpdate(**fields, current_password="wrong"), db, client)
        assert error.value.status_code == (429 if attempt == 5 else 403)
    with pytest.raises(HTTPException) as error:
        auth.update_profile(auth.ProfileUpdate(**fields, current_password="password123"), db, client)
    assert error.value.status_code == 429
    assert client.password_hash == original_hash and client.email is None


def test_profile_success_resets_failures(db):
    client = db.get(models.Client, 1)
    client.failed_login_count = 3
    db.commit()
    auth.update_profile(auth.ProfileUpdate(email="new@example.com", current_password="password123"), db, client)
    assert client.failed_login_count == 0


@pytest.mark.parametrize("kind", ["access", "mfa", "mfa_setup", "password_change", "step_up"])
def test_all_token_types_have_millisecond_issue_time(kind):
    payload = decode_token(create_typed_token(1, "Test", kind))
    assert payload["iat"] * 1000 <= payload["iat_ms"] < (payload["iat"] + 1) * 1000


@pytest.mark.parametrize("cutoff_set", [False, True])
def test_legacy_access_token_compatibility(db, cutoff_set):
    client = db.get(models.Client, 1)
    payload = decode_token(create_access_token(client.id, client.name))
    payload.pop("iat_ms")
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    if cutoff_set:
        client_service.revoke_tokens(db, client)
        with pytest.raises(HTTPException) as error:
            resolve(db, token)
        assert error.value.status_code == 401
    else:
        assert resolve(db, token).id == 1


@pytest.mark.parametrize("kind", ["mfa", "mfa_setup", "password_change"])
@pytest.mark.parametrize("legacy", [False, True])
def test_step_tokens_are_revoked_after_password_change(db, kind, legacy):
    if kind == "mfa":
        secret, _ = enroll(db)
    client = db.get(models.Client, 1)
    if kind == "password_change":
        client.must_change_password = True
        db.commit()
    step = login(db)["step_token"]
    if kind == "mfa_setup":
        setup = auth.start_enrollment(auth.StepRequest(step_token=step), db)
        secret = setup["manual_entry_key"]
    if legacy:
        payload = decode_token(step)
        payload.pop("iat_ms")
        step = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    if kind == "password_change":
        client_service.revoke_tokens(db, client)  # E.g. admin reset; stage still required.
    else:
        client_service.change_password(db, client, hash_password("changedpassword"))
    with pytest.raises(HTTPException) as error:
        if kind == "mfa":
            auth.verify_mfa_login(auth.MfaLoginVerifyRequest(
                mfa_token=step, code=pyotp.TOTP(secret).at(datetime.now(timezone.utc), counter_offset=1)), db)
        elif kind == "mfa_setup":
            auth.verify_enrollment(auth.EnrollVerifyRequest(step_token=step, code=pyotp.TOTP(secret).now()), db)
        else:
            auth.change_password(auth.PasswordChangeRequest(step_token=step, new_password="anotherpassword"), db)
    assert error.value.status_code == 401
    assert client.failed_login_count == 0


def test_totp_replay_and_next_window_including_stale_session(db, monkeypatch):
    from app.security import encrypt_key

    clock = [datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0] if tz else clock[0].replace(tzinfo=None)
        @classmethod
        def utcnow(cls):
            return clock[0].replace(tzinfo=None)
    monkeypatch.setattr(mfa_service, "datetime", Clock)
    client = db.get(models.Client, 1)
    setting = models.ClientMfaSetting(client_id=1, enabled=True,
                                    totp_secret_encrypted=encrypt_key("JBSWY3DPEHPK3PXP"))
    db.add(setting)
    db.commit()
    totp = pyotp.TOTP("JBSWY3DPEHPK3PXP")
    code = totp.at(clock[0])
    with Session(db.get_bind(), expire_on_commit=False) as stale_session:
        stale_setting = stale_session.get(models.ClientMfaSetting, setting.id)
        assert stale_setting.last_totp_step is None
        assert mfa_service.verify_mfa_factor(db, client, code=code)
        assert setting.last_totp_step == totp.timecode(clock[0])
        assert not mfa_service.verify_totp_code(stale_setting, code)
    assert not mfa_service.verify_mfa_factor(db, client, code=code)
    clock[0] += timedelta(seconds=30)
    assert mfa_service.verify_mfa_factor(db, client, code=totp.at(clock[0]))
    assert setting.last_totp_step == totp.timecode(clock[0])
    assert not mfa_service.verify_mfa_factor(db, client, code=code)  # Still in allowed time window.


def test_enrollment_code_is_consumed(db, monkeypatch):
    # Pin the clock: across a TOTP step boundary the sign-in code would legitimately be new.
    clock = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock if tz else clock.replace(tzinfo=None)
        @classmethod
        def utcnow(cls):
            return clock.replace(tzinfo=None)
    monkeypatch.setattr(mfa_service, "datetime", Clock)
    secret, _ = enroll(db, at=clock)
    step = login(db)
    with pytest.raises(HTTPException) as error:
        auth.verify_mfa_login(auth.MfaLoginVerifyRequest(mfa_token=step["mfa_token"], code=pyotp.TOTP(secret).at(clock)), db)
    assert error.value.status_code == 401
