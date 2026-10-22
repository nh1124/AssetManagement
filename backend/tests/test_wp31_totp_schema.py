"""WP31 schema and startup credential defaults."""
import asyncio
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app import models
from app.config import AppConfig, DEV_TOTP_SECRET
from app.database import Base
from app.security import decrypt_key, encrypt_key
from app.services import mfa_service


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add(models.Client(id=1, name="dev", username="dev", password_hash="unused"))
        session.commit()
        yield session
    engine.dispose()


def test_migration_adds_columns_with_safe_defaults_and_downgrades():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261022_0089_required_totp.py"
    spec = importlib.util.spec_from_file_location("wp31_totp", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261022_0088"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE clients (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE client_mfa_settings (id INTEGER PRIMARY KEY, client_id INTEGER, enabled BOOLEAN)"))
        connection.execute(sa.text("INSERT INTO clients VALUES (1), (2), (3)"))
        connection.execute(sa.text("INSERT INTO client_mfa_settings VALUES (1, 2, true), (2, 3, false)"))
        before = datetime.utcnow().replace(microsecond=0)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        after = datetime.utcnow()
        cutoffs = dict(connection.execute(sa.text(
            "SELECT id, tokens_valid_after FROM clients ORDER BY id"
        ).columns(tokens_valid_after=sa.DateTime())).all())
        assert before <= cutoffs[1] <= after  # No MFA row: existing sessions revoked.
        assert cutoffs[2] is None  # Enabled MFA: existing sessions untouched.
        assert cutoffs[3] == cutoffs[1]  # An unconfirmed/disabled row is insufficient.
        defaults = connection.execute(sa.text(
            "SELECT failed_login_count, locked_until, must_change_password FROM clients")).all()
        assert [tuple(row) for row in defaults] == [(0, None, 0)] * 3
        assert connection.execute(sa.text("SELECT pending_totp_secret_encrypted FROM client_mfa_settings")).scalars().all() == [None, None]
        assert connection.execute(sa.text("SELECT last_totp_step FROM client_mfa_settings")).scalars().all() == [None, None]
        mfa_columns = {col["name"]: col for col in sa.inspect(connection).get_columns("client_mfa_settings")}
        assert mfa_columns["last_totp_step"]["nullable"]
        assert isinstance(mfa_columns["last_totp_step"]["type"], sa.BigInteger)
        columns = {col["name"]: col for col in sa.inspect(connection).get_columns("clients")}
        assert not columns["failed_login_count"]["nullable"] and not columns["must_change_password"]["nullable"]
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert [col["name"] for col in sa.inspect(connection).get_columns("clients")] == ["id"]
        assert [col["name"] for col in sa.inspect(connection).get_columns("client_mfa_settings")] == ["id", "client_id", "enabled"]
    engine.dispose()


def test_development_mfa_enables_fixed_secret_and_recovers_exhausted_codes(db):
    client = db.get(models.Client, 1)
    mfa_service.ensure_development_mfa(db, client)
    setting = mfa_service.get_mfa_setting(db, client)
    assert setting.enabled and decrypt_key(setting.totp_secret_encrypted) == DEV_TOTP_SECRET
    codes = db.query(models.ClientRecoveryCode).all()
    assert len(codes) == 8
    old_hashes = {code.code_hash for code in codes}
    mfa_service.ensure_development_mfa(db, client)
    assert {code.code_hash for code in db.query(models.ClientRecoveryCode)} == old_hashes
    for row in db.query(models.ClientRecoveryCode):
        row.used_at = datetime.utcnow()
    db.commit()
    mfa_service.ensure_development_mfa(db, client)
    assert mfa_service.mfa_status(db, client)["recovery_codes_remaining"] == 8
    assert {code.code_hash for code in db.query(models.ClientRecoveryCode)}.isdisjoint(old_hashes)


@pytest.mark.parametrize("active,enabled", [(True, True), (True, False), (False, True), (False, False)])
def test_production_guard_checks_every_active_client_not_only_dev(db, active, enabled):
    db.add(models.Client(id=2, name="Owner", username="owner", is_active=active))
    db.add(models.ClientMfaSetting(client_id=2, enabled=enabled, totp_secret_encrypted=encrypt_key(DEV_TOTP_SECRET)))
    db.commit()
    if active:
        with pytest.raises(RuntimeError, match="development TOTP secret"):
            mfa_service.ensure_no_development_totp(db)
    else:
        mfa_service.ensure_no_development_totp(db)


def configure_startup(db, monkeypatch, production):
    from app import database, main

    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    monkeypatch.setattr(main, "install_db_audit", lambda factory: None)
    monkeypatch.setattr(main, "install_sql_timing", lambda engine: None)
    monkeypatch.setattr(main, "settings", AppConfig(
        app_env="production" if production else "development", jwt_secret_key="production-key",
        mcp_jwt_secret="production-mcp-key", encryption_key="production-key", allowed_origins="https://example.com",
    ))
    async def no_background_work():
        pass
    monkeypatch.setattr(main, "run_automatic_recording_loop", no_background_work)
    return main


@pytest.mark.parametrize("production", [False, True])
def test_startup_seeds_development_mfa_only_in_development(db, monkeypatch, production):
    main = configure_startup(db, monkeypatch, production)
    async def run():
        await main.startup_event()
        await main.shutdown_event()
    asyncio.run(run())
    client = db.get(models.Client, 1)
    setting = mfa_service.get_mfa_setting(db, client)
    if production:
        assert setting is None
    else:
        assert setting.enabled and decrypt_key(setting.totp_secret_encrypted) == DEV_TOTP_SECRET
        assert mfa_service.mfa_status(db, client)["recovery_codes_remaining"] == 8


def test_production_startup_refuses_development_factor(db, monkeypatch):
    db.add(models.ClientMfaSetting(client_id=1, enabled=True, totp_secret_encrypted=encrypt_key(DEV_TOTP_SECRET)))
    db.commit()
    main = configure_startup(db, monkeypatch, True)
    with pytest.raises(RuntimeError, match="development TOTP secret"):
        asyncio.run(main.startup_event())
