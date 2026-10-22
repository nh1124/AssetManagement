"""Replacing ENCRYPTION_KEY must not lock anyone out.

The key protects the TOTP secrets, so a rotation that makes them unreadable is
an MFA lockout. These tests walk the rotation in the order it is performed.
"""
from __future__ import annotations

import sys

import pyotp
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, security
from backend.app.config import AppConfig
from backend.app.database import Base
from backend.app.maintenance.reencrypt_secrets import reencrypt
from backend.app.services import mfa_service

OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()


def use_keys(monkeypatch, keys: list[str]) -> None:
    """Make these the configured keys. Under the conftest shim the security
    module can be loaded twice (app.security for `from .. import security`,
    backend.app.security for `from ..security import ...`), so set both."""
    fernet = security.build_fernet(keys)
    for name in ("app.security", "backend.app.security"):
        if name in sys.modules:
            monkeypatch.setattr(sys.modules[name], "fernet", fernet)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def stored_under_old_key(db, monkeypatch):
    """A client with an enabled TOTP secret, encrypted while OLD_KEY was the
    only key."""
    use_keys(monkeypatch, [OLD_KEY])
    totp_secret = pyotp.random_base32()
    client = models.Client(name="owner", username="owner", password_hash="hash")
    db.add(client)
    db.flush()
    db.add(models.ClientMfaSetting(
        client_id=client.id, enabled=True, totp_secret_encrypted=security.encrypt_key(totp_secret),
    ))
    db.commit()
    return client, totp_secret


def stored_secret(db, client) -> str:
    return db.query(models.ClientMfaSetting).filter_by(client_id=client.id).one().totp_secret_encrypted


def test_previous_keys_are_listed_after_the_current_one():
    settings = AppConfig(encryption_key=NEW_KEY, encryption_key_previous=f" {OLD_KEY} ,,{NEW_KEY}")
    assert settings.encryption_keys == [NEW_KEY, OLD_KEY]
    assert AppConfig(encryption_key=NEW_KEY).encryption_keys == [NEW_KEY]


def test_with_the_old_key_kept_as_previous_nothing_stops_working(db, stored_under_old_key, monkeypatch):
    client, totp_secret = stored_under_old_key
    use_keys(monkeypatch, [NEW_KEY, OLD_KEY])

    assert mfa_service.verify_mfa_factor(db, client, code=pyotp.TOTP(totp_secret).now())
    # New values are written under the new key already.
    assert Fernet(NEW_KEY.encode()).decrypt(security.encrypt_key("fresh").encode()) == b"fresh"


def test_reencrypting_lets_the_old_key_be_dropped(db, stored_under_old_key, monkeypatch):
    client, totp_secret = stored_under_old_key
    use_keys(monkeypatch, [NEW_KEY, OLD_KEY])

    assert reencrypt(db, apply=True) == {"rotated": 1, "unreadable": 0}

    use_keys(monkeypatch, [NEW_KEY])
    db.expire_all()
    assert mfa_service.verify_mfa_factor(db, client, code=pyotp.TOTP(totp_secret).now())


def test_a_dry_run_changes_nothing(db, stored_under_old_key, monkeypatch):
    client, _ = stored_under_old_key
    before = stored_secret(db, client)
    use_keys(monkeypatch, [NEW_KEY, OLD_KEY])

    assert reencrypt(db, apply=False) == {"rotated": 1, "unreadable": 0}
    db.expire_all()
    assert stored_secret(db, client) == before


def test_a_value_no_key_can_read_is_reported_and_left_alone(db, stored_under_old_key, monkeypatch):
    client, _ = stored_under_old_key
    before = stored_secret(db, client)
    # The old key was dropped before re-encrypting: the mistake to catch.
    use_keys(monkeypatch, [NEW_KEY])

    assert reencrypt(db, apply=True) == {"rotated": 0, "unreadable": 1}
    db.expire_all()
    assert stored_secret(db, client) == before


@pytest.mark.parametrize("apply", [False, True])
def test_pending_factor_is_reencrypted_even_without_an_active_secret(db, monkeypatch, apply):
    use_keys(monkeypatch, [OLD_KEY])
    secret = pyotp.random_base32()
    client = models.Client(name="pending-owner")
    db.add(client)
    db.flush()
    row = models.ClientMfaSetting(client_id=client.id, pending_totp_secret_encrypted=security.encrypt_key(secret))
    db.add(row)
    db.commit()
    before = row.pending_totp_secret_encrypted
    use_keys(monkeypatch, [NEW_KEY, OLD_KEY])
    assert reencrypt(db, apply=apply) == {"rotated": 1, "unreadable": 0}
    db.refresh(row)
    if apply:
        assert Fernet(NEW_KEY.encode()).decrypt(row.pending_totp_secret_encrypted.encode()).decode() == secret
    else:
        assert row.pending_totp_secret_encrypted == before
