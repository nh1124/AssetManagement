"""WP32 public auth gates exercised through the actual staged HTTP endpoints."""
from datetime import datetime, timezone

import pyotp
import pytest

from app import models
from app.services import system_settings_service as settings
from app.workflows import admin_account_workflow as workflow
from app.utils.jwt import create_access_token

from test_wp31_auth_http import http, bearer, enroll, sign_in  # noqa: F401


@pytest.mark.parametrize("language", ["en", "ja"])
@pytest.mark.parametrize("mode", ["open", "approval", "closed"])
def test_registration_modes_http(http, mode, language):
    request, sessions = http
    with sessions() as db:
        settings.set(db, "registration_mode", mode, "cli:test")
    response = request("POST", "/auth/register", headers={"Accept-Language": language},
                       json={"username": "new", "password": "password123"})
    if mode == "open":
        assert response.status_code == 200 and response.json()["next_step"] == "mfa_setup"
    elif mode == "approval":
        assert response.status_code == 202
        assert response.json() == {"approval_pending": True, "message": (
            "Your account was created and is waiting for approval." if language == "en"
            else "アカウントを作成しました。管理者の承認をお待ちください。")}
        assert "step_token" not in response.json()
        with sessions() as db:
            assert db.query(models.Client).filter_by(username="new").one().approval_pending
        # Password still has to match before the account's pending state is revealed.
        assert request("POST", "/auth/login", json={"username": "new", "password": "incorrect"}).status_code == 401
        login = request("POST", "/auth/login", headers={"Accept-Language": language},
                        json={"username": "new", "password": "password123"})
        assert login.status_code == 403
        assert login.json() == {"detail": "This account is waiting for approval." if language == "en"
                                else "このアカウントは管理者の承認待ちです。"}
        with sessions() as db:
            client = db.query(models.Client).filter_by(username="new").one()
            workflow.client_approve(db, client.id, actor="cli:test")
        assert request("POST", "/auth/login", json={"username": "new", "password": "password123"}).json()["next_step"] == "mfa_setup"
    else:
        assert response.status_code == 403
        assert response.json() == {"detail": "Sign-up is closed." if language == "en" else "現在、新規登録は受け付けていません。"}
        with sessions() as db:
            assert db.query(models.Client).filter_by(username="new").first() is None


def test_pending_refuses_access_existing_step_and_mcp_exchange(http):
    from app.config import settings as config
    from jose import jwt

    request, sessions = http
    step = sign_in(request)
    token = create_access_token(1, "Tester")
    mcp_token = jwt.encode({"sub": "tester", "username": "tester", "backend_client_id": 1, "type": "access",
                            "aud": config.mcp_token_audience, "iss": config.allowed_mcp_token_issuers[0],
                            "auth_time_ms": datetime.now(timezone.utc).timestamp() * 1000},
                           config.mcp_jwt_secret, algorithm=config.jwt_algorithm)
    with sessions() as db:
        db.get(models.Client, 1).approval_pending = True
        db.commit()
    assert request("GET", "/me", headers=bearer(token)).status_code == 403
    assert request("POST", "/auth/enroll/start", json={"step_token": step["step_token"]}).status_code == 403
    assert request("POST", "/auth/mcp/exchange", json={"mcp_access_token": mcp_token}).status_code == 403


def test_admin_reset_mfa_requires_password_change_then_totp_setup_http(http):
    request, sessions = http
    _, prior = enroll(request)
    with sessions() as db:
        temporary = workflow.client_reset_mfa(db, 1, actor="cli:test")
    assert request("GET", "/me", headers=bearer(prior["access_token"])).status_code == 401
    assert request("POST", "/auth/login", json={"username": "tester", "password": "password123"}).status_code == 401
    login = request("POST", "/auth/login", json={"username": "tester", "password": temporary})
    assert login.status_code == 200
    assert login.json()["next_step"] == "password_change" and login.json()["access_token"] is None
    assert request("GET", "/me", headers=bearer(login.json()["step_token"])).status_code == 401
    changed = request("POST", "/auth/password-change", json={"step_token": login.json()["step_token"], "new_password": "differentpassword"})
    assert changed.status_code == 200 and changed.json()["next_step"] == "mfa_setup"
    setup = request("POST", "/auth/enroll/start", json={"step_token": changed.json()["step_token"]})
    assert setup.status_code == 200
    completed = request("POST", "/auth/enroll/verify", json={"step_token": changed.json()["step_token"],
                        "code": pyotp.TOTP(setup.json()["manual_entry_key"]).now()})
    assert completed.status_code == 200 and completed.json()["access_token"]
    assert request("GET", "/me", headers=bearer(completed.json()["access_token"])).status_code == 200
    with sessions() as db:
        assert not db.get(models.Client, 1).must_change_password
        logs = db.query(models.AdminAuditLog).filter_by(action="client.reset_mfa").all()
        assert len(logs) == 1 and temporary not in str(logs[0].detail)


def test_login_lockout_setting_is_used_over_http(http):
    request, sessions = http
    with sessions() as db:
        settings.set(db, "login_lockout_threshold", 3, "cli:test")
    for attempt in range(3):
        assert request("POST", "/auth/login", json={"username": "tester", "password": "wrong"}).status_code == (429 if attempt == 2 else 401)
