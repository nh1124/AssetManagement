import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.config import (
    DEV_ENCRYPTION_KEY,
    DEV_JWT_SECRET_KEY,
    DEV_MCP_JWT_SECRET,
    AppConfig,
)
from backend.app.database import Base
from backend.app.main import ensure_no_default_admin_password
from backend.app.models import Client
from backend.app.utils.password import hash_password


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_development_allows_local_defaults() -> None:
    settings = AppConfig(app_env="development")

    settings.validate_production_settings()


def test_production_rejects_development_secrets() -> None:
    settings = AppConfig(
        app_env="production",
        jwt_secret_key=DEV_JWT_SECRET_KEY,
        encryption_key=DEV_ENCRYPTION_KEY,
        allowed_origins="https://asset.example",
    )

    with pytest.raises(RuntimeError) as exc:
        settings.validate_production_settings()

    message = str(exc.value)
    assert "JWT_SECRET_KEY" in message
    assert "MCP_JWT_SECRET" in message
    assert "ENCRYPTION_KEY" in message


def test_production_rejects_development_mcp_secret() -> None:
    settings = AppConfig(
        app_env="production",
        jwt_secret_key="prod-jwt-secret-that-is-long-and-unique",
        mcp_jwt_secret=DEV_MCP_JWT_SECRET,
        encryption_key="prod-fernet-key-placeholder-for-config-test",
        allowed_origins="https://asset.example",
    )

    with pytest.raises(RuntimeError) as exc:
        settings.validate_production_settings()

    assert "MCP_JWT_SECRET" in str(exc.value)


def test_production_rejects_wildcard_cors() -> None:
    settings = AppConfig(
        app_env="production",
        jwt_secret_key="prod-jwt-secret-that-is-long-and-unique",
        mcp_jwt_secret="prod-mcp-secret-that-is-long-and-unique",
        encryption_key="prod-fernet-key-placeholder-for-config-test",
        allowed_origins="*",
    )

    with pytest.raises(RuntimeError) as exc:
        settings.validate_production_settings()

    assert "ALLOWED_ORIGINS" in str(exc.value)


def test_allowed_origins_are_parsed_from_csv() -> None:
    settings = AppConfig(
        allowed_origins="https://asset.example, http://localhost:5173 ,,",
    )

    assert settings.cors_allowed_origins == [
        "https://asset.example",
        "http://localhost:5173",
    ]


def test_development_expands_local_mcp_issuer_scheme_variants() -> None:
    settings = AppConfig(
        app_env="development",
        mcp_allowed_issuers="http://localhost:13000,https://asset.example",
        mcp_base_url="https://asset-mcp.example.com/",
    )

    assert settings.allowed_mcp_token_issuers == [
        "http://localhost:13000",
        "https://asset.example",
        "https://asset-mcp.example.com",
        "https://localhost:13000",
    ]


def test_default_admin_password_is_rejected() -> None:
    db = _session()
    try:
        db.add(Client(name="Default User", username="admin", password_hash=hash_password("adminadmin")))
        db.commit()

        with pytest.raises(RuntimeError) as exc:
            ensure_no_default_admin_password(db)

        assert "default admin password" in str(exc.value)
    finally:
        db.close()


def test_non_default_or_inactive_admin_password_is_allowed() -> None:
    db = _session()
    try:
        db.add_all([
            Client(name="Inactive Admin", username="admin", password_hash=hash_password("adminadmin"), is_active=False),
            Client(name="Owner", username="owner", password_hash=hash_password("adminadmin")),
        ])
        db.commit()

        ensure_no_default_admin_password(db)
    finally:
        db.close()
