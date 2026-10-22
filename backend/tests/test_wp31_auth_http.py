"""HTTP contract for WP31, using ASGI transport (no AnyIO blocking portal)."""
import asyncio
from datetime import datetime, timezone

import httpx
import pyotp
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.main import app as main_app
from app.routers import auth
from app.utils.jwt import create_typed_token, decode_token
from app.utils.password import hash_password


@pytest.fixture
def http():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        db.add(models.Client(id=1, name="Tester", username="tester", password_hash=hash_password("password123")))
        db.commit()
    app = FastAPI(exception_handlers=main_app.exception_handlers)
    app.include_router(auth.router)

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
                pending = asyncio.create_task(client.request(method, path, **kwargs))
                # Same selector wakeup used by the repository's read endpoint tests.
                deadline = asyncio.get_running_loop().time() + 30
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.01)
                    if asyncio.get_running_loop().time() >= deadline:
                        pending.cancel()
                        raise AssertionError(f"{method} {path} did not complete")
                return pending.result()
        return asyncio.run(run())
    yield request, sessions
    engine.dispose()


def sign_in(request):
    result = request("POST", "/auth/login", json={"username": "tester", "password": "password123"})
    assert result.status_code == 200, result.text
    return result.json()


def enroll(request):
    step = sign_in(request)
    setup = request("POST", "/auth/enroll/start", json={"step_token": step["step_token"]}).json()
    result = request("POST", "/auth/enroll/verify", json={"step_token": step["step_token"],
                     "code": pyotp.TOTP(setup["manual_entry_key"]).now()})
    assert result.status_code == 200, result.text
    return setup["manual_entry_key"], result.json()


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_login_enroll_and_existing_mfa_http(http):
    request, _ = http
    step = sign_in(request)
    assert set(step) == {"access_token", "token_type", "client_id", "name", "next_step", "step_token"}
    assert step["access_token"] is None and step["next_step"] == "mfa_setup" and step["token_type"] == "step"
    assert request("GET", "/me", headers=bearer(step["step_token"])).status_code == 401
    secret, result = enroll(request)
    assert set(result) == {"recovery_codes", "access_token", "token_type", "client_id", "name"}
    assert len(result["recovery_codes"]) == 8 and result["token_type"] == "bearer"
    assert request("GET", "/me", headers=bearer(result["access_token"])).status_code == 200
    step = sign_in(request)
    assert step["next_step"] == "mfa" and step["mfa_required"] is True
    assert step["step_token"] == step["mfa_token"]
    result = request("POST", "/auth/mfa/login/verify", json={"mfa_token": step["mfa_token"], "recovery_code": result["recovery_codes"][0]})
    assert result.status_code == 200 and result.json()["token_type"] == "bearer"
    assert request("GET", "/me", headers=bearer(result.json()["access_token"])).status_code == 200


def test_register_only_issues_enrollment_step_http(http):
    request, _ = http
    result = request("POST", "/auth/register", json={"username": "new", "password": "password123"})
    assert result.status_code == 200
    assert result.json()["next_step"] == "mfa_setup" and result.json()["access_token"] is None
    assert "mfa_required" not in result.json() and "mfa_token" not in result.json()


def test_required_password_change_http(http):
    request, sessions = http
    with sessions() as db:
        db.get(models.Client, 1).must_change_password = True
        db.commit()
    step = sign_in(request)
    assert step["next_step"] == "password_change"
    assert request("GET", "/me", headers=bearer(step["step_token"])).status_code == 401
    result = request("POST", "/auth/password-change", json={"step_token": step["step_token"], "new_password": "newpassword123"})
    assert result.status_code == 200
    assert result.json()["next_step"] == "mfa_setup" and result.json()["access_token"] is None
    with sessions() as db:
        assert not db.get(models.Client, 1).must_change_password
        assert db.get(models.Client, 1).tokens_valid_after is not None


def test_every_step_endpoint_rejects_other_token_types_http(http):
    request, _ = http
    endpoints = [
        ("/auth/password-change", "password_change", "step_token", {"new_password": "newpassword123"}),
        ("/auth/enroll/start", "mfa_setup", "step_token", {}),
        ("/auth/enroll/verify", "mfa_setup", "step_token", {"code": "123456"}),
        ("/auth/mfa/login/verify", "mfa", "mfa_token", {"code": "123456"}),
    ]
    for path, expected, key, fields in endpoints:
        for kind in ("password_change", "mfa_setup", "mfa", "access", "step_up"):
            if kind == expected:
                continue
            token = create_typed_token(1, "Tester", kind)
            assert request("POST", path, json={key: token, **fields}).status_code == 401
    for kind in ("password_change", "mfa_setup", "mfa"):
        assert request("GET", "/me", headers=bearer(create_typed_token(1, "Tester", kind))).status_code == 401


@pytest.mark.parametrize("path", ["/auth/mfa/disable", "/auth/mfa/setup/start", "/auth/mfa/setup/verify"])
def test_removed_routes_http(http, path):
    request, _ = http
    assert request("POST", path, json={}).status_code in (404, 405)


def test_lockout_localized_and_persisted_across_requests_http(http):
    request, sessions = http
    for attempt in range(5):
        response = request("POST", "/auth/login", json={"username": "tester", "password": "wrong"})
        assert response.status_code == (429 if attempt == 4 else 401)
    for language, message in (("en", auth.LOCKED.en), ("ja", auth.LOCKED.ja)):
        result = request("POST", "/auth/login", headers={"Accept-Language": language},
                         json={"username": "tester", "password": "password123"})
        assert result.status_code == 429 and result.json() == {"detail": message}
    with sessions() as db:
        assert db.get(models.Client, 1).failed_login_count == 5


def test_replacement_and_profile_return_working_access_tokens_http(http):
    from jose import jwt
    from app.config import settings

    request, sessions = http
    secret, completed = enroll(request)
    token = completed["access_token"]
    payload = decode_token(token)
    payload["iat"] -= 30
    payload["iat_ms"] -= 30000
    old_token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    headers = bearer(token)
    assert request("POST", "/auth/mfa/replace/start", headers=headers,
                   json={"current_password": "password123"}).status_code == 401
    setup = request("POST", "/auth/mfa/replace/start", headers=headers, json={"recovery_code": completed["recovery_codes"][0]})
    assert setup.status_code == 200
    step = sign_in(request)
    assert request("POST", "/auth/mfa/login/verify", json={"mfa_token": step["mfa_token"],
                   "recovery_code": completed["recovery_codes"][1]}).status_code == 200
    replaced = request("POST", "/auth/mfa/replace/verify", headers=headers,
                       json={"code": pyotp.TOTP(setup.json()["manual_entry_key"]).at(datetime.now(timezone.utc), counter_offset=1)})
    assert replaced.status_code == 200
    assert set(replaced.json()) == {"recovery_codes", "access_token", "token_type"}
    assert set(replaced.json()["recovery_codes"]).isdisjoint(completed["recovery_codes"])
    assert request("GET", "/me", headers=bearer(old_token)).status_code == 401
    headers = bearer(replaced.json()["access_token"])
    assert request("GET", "/me", headers=headers).status_code == 200
    changed = request("PATCH", "/auth/me", headers=headers, json={"password": "changedpassword", "current_password": "password123"})
    assert changed.status_code == 200 and changed.json()["access_token"]
    assert request("GET", "/me", headers=bearer(changed.json()["access_token"])).status_code == 200
    with sessions() as db:
        assert db.get(models.Client, 1).tokens_valid_after is not None
