"""Process-specific production validation and explicit dev origin boundaries."""
import asyncio

import httpx
import pytest
from cryptography.fernet import Fernet

from app.admin.main import create_app
from app.config import AppConfig, DEV_ENCRYPTION_KEY, DEV_JWT_SECRET_KEY, DEV_MCP_JWT_SECRET


def request(app, method, url, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            pending = asyncio.create_task(client.request(method, url, **kwargs))
            deadline = asyncio.get_running_loop().time() + 30
            while not pending.done():
                await asyncio.wait({pending}, timeout=0.01)
                if asyncio.get_running_loop().time() > deadline:
                    pending.cancel()
                    raise AssertionError(f'{method} {url} timed out')
            return pending.result()
    return asyncio.run(run())


def production_config(**overrides):
    return AppConfig(_env_file=None, **{
        "app_env": "production",
        "encryption_key": Fernet.generate_key().decode(),
        "jwt_secret_key": DEV_JWT_SECRET_KEY,
        "mcp_jwt_secret": DEV_MCP_JWT_SECRET,
        # User-plane origins are irrelevant to the admin process.
        "allowed_origins": "*",
        **overrides,
    })


def test_admin_production_starts_without_user_token_keys():
    config = production_config()
    app = create_app(config)
    assert app.state.config is config
    # The backend still rejects the same user-plane configuration.
    with pytest.raises(RuntimeError) as exc:
        config.validate_production_settings()
    assert "JWT_SECRET_KEY" in str(exc.value)
    assert "MCP_JWT_SECRET" in str(exc.value)
    assert "ALLOWED_ORIGINS" in str(exc.value)


@pytest.mark.parametrize("key,value", [
    ("encryption_key", DEV_ENCRYPTION_KEY),
    ("encryption_key", ""),
    ("admin_allowed_hosts", "*"),
    ("admin_allowed_hosts", "*.example.com"),
    ("admin_allowed_hosts", " , "),
    ("admin_allowed_origins", "*"),
    ("admin_allowed_origins", "https://*.example.com"),
    ("admin_allowed_origins", " , "),
])
def test_admin_production_rejects_unsafe_configuration(key, value):
    with pytest.raises(RuntimeError, match=key.upper()):
        create_app(production_config(**{key: value}))


@pytest.mark.parametrize("explicit_origin,expected", [(False, 403), (True, 404)])
def test_dev_server_origin_requires_explicit_allowlist(monkeypatch, explicit_origin, expected):
    # POST to an absent route exercises the guard without DB access or TestClient.
    dev_origin = "http://admin.localhost:15380"
    monkeypatch.delenv("ADMIN_ALLOWED_ORIGINS", raising=False)
    if explicit_origin:
        monkeypatch.setenv("ADMIN_ALLOWED_ORIGINS", f"http://admin.localhost:18300, {dev_origin}")
    app = create_app(AppConfig(_env_file=None, app_env="development"))

    response = request(app, "POST", "http://admin.localhost/admin/api/missing", headers={"Origin": dev_origin})
    assert response.status_code == expected


@pytest.mark.parametrize("host,expected", [("admin.localhost", 200), ("127.0.0.1", 400), ("localhost", 400)])
def test_default_host_boundary(monkeypatch, host, expected):
    monkeypatch.delenv("ADMIN_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("ADMIN_ALLOWED_ORIGINS", raising=False)
    config = AppConfig(_env_file=None)
    assert config.admin_allowed_hosts == "admin.localhost"
    assert config.admin_allowed_origins == "http://admin.localhost:18300"
    app = create_app(config)

    response = request(app, "GET", f"http://{host}:18300/health")
    assert response.status_code == expected
    assert "set-cookie" not in response.headers
