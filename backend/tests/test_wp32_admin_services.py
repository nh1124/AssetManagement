from datetime import date, datetime, timedelta
import hashlib
import json

import pyotp
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import models, security
from app.database import Base
from app.domain.admin_permissions import ALL_PERMISSIONS, PRESETS, STEP_UP_REQUIRED, validate_permissions
from app.domain.errors import Invalid, Refused
from app.maintenance.reencrypt_secrets import reencrypt
from app.services import admin_auth_service as admins, admin_audit_service as audit, client_service as clients
from app.services import mfa_service, system_settings_service as settings
from app.utils.password import hash_password, verify_password
from app.utils.temporary_password import ALPHABET
from app.workflows import admin_account_workflow as workflow

ACTOR = "cli:test"
PASSWORD = "a sufficiently long password"


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()


def owner(db, username="owner"):
    return workflow.admin_create(db, username, PASSWORD, permissions=PRESETS["owner"], actor=ACTOR)[0]


def test_permission_vocabulary_and_presets():
    assert ALL_PERMISSIONS == {"accounts.read", "accounts.manage", "accounts.credentials", "accounts.export",
        "accounts.delete", "health.read", "health.repair", "audit.read", "settings.manage", "ops.read", "ops.run", "admins.manage"}
    assert STEP_UP_REQUIRED == {"accounts.credentials", "accounts.export", "accounts.delete", "health.repair",
                                "settings.manage", "ops.run", "admins.manage"}
    assert PRESETS["owner"] == ALL_PERMISSIONS
    assert PRESETS["support"] == {"accounts.read", "accounts.manage", "health.read", "audit.read"}
    assert PRESETS["viewer"] == {p for p in ALL_PERMISSIONS if p.endswith(".read")}
    with pytest.raises(Invalid):
        validate_permissions(["accounts.typo"])


def test_setting_defaults_metadata_and_explicit_default(db):
    expected = {"registration_mode": "open", "account_deletion_grace_days": 30,
                "login_lockout_threshold": 5, "login_lockout_minutes": 15}
    assert {key: settings.get(db, key) for key in expected} == expected
    assert db.query(models.SystemSetting).count() == 0
    for key, value in expected.items():
        assert settings.all(db)[key] == {"value": value, "default": value, "updated_at": None, "updated_by": None}
        workflow.settings_set(db, key, value, actor=ACTOR)
        assert settings.all(db)[key]["updated_by"] == ACTOR
        assert settings.all(db)[key]["updated_at"] is not None
    assert db.query(models.SystemSetting).count() == 4
    assert {row.action for row in audit.list_logs(db)} == {"settings.set"}


@pytest.mark.parametrize("key,value", [
    ("registration_mode", "open"), ("registration_mode", "approval"), ("registration_mode", "closed"),
    ("account_deletion_grace_days", 1), ("account_deletion_grace_days", 365),
    ("login_lockout_threshold", 3), ("login_lockout_threshold", 20),
    ("login_lockout_minutes", 1), ("login_lockout_minutes", 1440),
])
def test_setting_valid_boundaries(db, key, value):
    assert settings.set(db, key, value, ACTOR) == settings.get(db, key) == value


@pytest.mark.parametrize("key,value", [
    ("registration_mode", "unknown"), ("registration_mode", []), ("registration_mode", True),
    ("account_deletion_grace_days", 0), ("account_deletion_grace_days", 366),
    ("login_lockout_threshold", 2), ("login_lockout_threshold", 21),
    ("login_lockout_minutes", 0), ("login_lockout_minutes", 1441),
    ("login_lockout_threshold", True), ("login_lockout_threshold", 3.0), ("login_lockout_minutes", "15"),
    ("unknown", 1),
])
def test_setting_invalid_values(db, key, value):
    with pytest.raises(Invalid):
        settings.set(db, key, value, ACTOR)
    assert db.query(models.SystemSetting).count() == 0


@pytest.mark.parametrize("operation", [lambda db: settings.get(db, "unknown"), lambda db: settings.set(db, "unknown", 1, ACTOR)])
def test_unknown_setting_rejected(db, operation):
    with pytest.raises(Invalid):
        operation(db)


def test_every_client_operation_and_audit_are_atomic_and_secret_free(db):
    commits = []
    sa.event.listen(db, "after_commit", lambda session: commits.append(True))
    client, temporary = workflow.client_create(db, "TEST", "Name", "E@EXAMPLE.COM", actor=ACTOR)
    assert len(temporary) == 16 and set(temporary) <= set(ALPHABET)
    assert client.username == "test" and client.email == "e@example.com"
    assert verify_password(temporary, client.password_hash) and client.must_change_password
    assert len(commits) == 1
    assert audit.list_logs(db)[0].target_client_id == client.id
    workflow.client_suspend(db, client.id, "At user request", actor=ACTOR)
    assert not client.is_active and client.suspended_reason == "At user request" and client.tokens_valid_after
    workflow.client_reactivate(db, client.id, actor=ACTOR)
    assert client.is_active and client.suspended_reason is None
    client.approval_pending = True
    db.commit()
    workflow.client_approve(db, client.id, actor=ACTOR)
    assert not client.approval_pending
    client.locked_until, client.failed_login_count = datetime.utcnow() + timedelta(minutes=15), 5
    db.commit()
    workflow.client_unlock(db, client.id, actor=ACTOR)
    assert client.locked_until is None and client.failed_login_count == 0
    previous = client.tokens_valid_after
    workflow.client_sign_out(db, client.id, actor=ACTOR)
    assert client.tokens_valid_after >= previous
    password = workflow.client_reset_password(db, client.id, actor=ACTOR)
    assert password != temporary and client.must_change_password and verify_password(password, client.password_hash)
    secret = mfa_service.start_totp_setup(db, client)["manual_entry_key"]
    codes = mfa_service.verify_totp_setup(db, client, pyotp.TOTP(secret).now())
    reset = workflow.client_reset_mfa(db, client.id, actor=ACTOR)
    assert verify_password(reset, client.password_hash) and client.must_change_password
    assert not mfa_service.mfa_enabled(db, client.id)
    assert mfa_service.get_mfa_setting(db, client) is None and db.query(models.ClientRecoveryCode).count() == 0
    logs = audit.list_logs(db)
    assert {row.action for row in logs} == {"client." + suffix for suffix in (
        "create", "suspend", "reactivate", "approve", "unlock", "sign_out", "reset_password", "reset_mfa")}
    details = json.dumps([row.detail for row in logs])
    for sensitive in [temporary, password, reset, secret, client.password_hash, *codes]:
        assert sensitive not in details
    assert all(row.actor == ACTOR and row.result == "ok" for row in logs)


def test_client_operation_rolls_back_when_audit_fails(db, monkeypatch):
    client, _ = workflow.client_create(db, "test", "Test", actor=ACTOR)
    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(RuntimeError):
        workflow.client_suspend(db, client.id, "reason", actor=ACTOR)
    db.refresh(client)
    assert client.is_active and client.suspended_reason is None


def test_client_summary_uses_one_grouped_query_and_never_returns_records(db):
    for i in range(1, 5):
        db.add(models.Client(id=i, name=f"Name {i}", username=f"user{i}"))
    db.flush()
    db.add_all([models.Transaction(client_id=i, date=date(2026, 10, j), description="private", amount_minor=100)
                for i in range(1, 5) for j in range(1, i + 1)])
    db.add(models.ClientMfaSetting(client_id=1, enabled=True))
    db.commit()
    statements = []
    def record(conn, cursor, statement, *args):
        statements.append(statement)
    sa.event.listen(db.bind, "before_cursor_execute", record)
    try:
        rows = clients.admin_list(db, limit=10, offset=0)
    finally:
        sa.event.remove(db.bind, "before_cursor_execute", record)
    tx_reads = [sql for sql in statements if "FROM transactions" in sql]
    assert len(tx_reads) == 1 and "GROUP BY" in tx_reads[0]
    assert [row["transaction_count"] for row in rows] == [1, 2, 3, 4]
    assert [row["last_transaction_date"] for row in rows] == [date(2026, 10, i) for i in range(1, 5)]
    assert rows[0]["mfa_enabled"] and not rows[1]["mfa_enabled"]
    assert "private" not in str(rows) and "password_hash" not in str(rows)
    assert clients.admin_summary(db, db.get(models.Client, 1)) == rows[0]
    assert clients.admin_list(db, query="USER2", limit=10, offset=0)[0]["id"] == 2
    assert len(clients.admin_list(db, limit=1, offset=2)) == 1
    assert not clients.admin_list(db, query="%", limit=10, offset=0)
    client = db.get(models.Client, 2)
    client.approval_pending = True
    db.get(models.Client, 3).is_active = False
    db.get(models.Client, 4).locked_until = datetime.utcnow() + timedelta(minutes=1)
    db.commit()
    for status, ids in [("pending", [2]), ("suspended", [3]), ("locked", [4]), ("active", [1, 4])]:
        assert [row["id"] for row in clients.admin_list(db, status=status, limit=10, offset=0)] == ids


def test_client_lockout_reads_settings_each_time(db):
    client, _ = workflow.client_create(db, "test", "Test", actor=ACTOR)
    settings.set(db, "login_lockout_threshold", 3, ACTOR)
    settings.set(db, "login_lockout_minutes", 2, ACTOR)
    before = datetime.utcnow()
    for i in range(3):
        clients.record_auth_failure(db, client)
        assert clients.is_locked(client) == (i == 2)
    assert before + timedelta(minutes=2) <= client.locked_until <= datetime.utcnow() + timedelta(minutes=2)


@pytest.mark.parametrize("operation", [
    lambda db, admin: workflow.admin_disable(db, admin.id, actor=ACTOR),
    lambda db, admin: workflow.admin_revoke(db, admin.id, ["admins.manage"], actor=ACTOR),
    lambda db, admin: workflow.admin_set_permissions(db, admin.id, PRESETS["viewer"], actor=ACTOR),
])
def test_last_manager_refusal_is_persisted_in_audit(db, operation):
    admin = owner(db)
    with pytest.raises(Refused):
        operation(db, admin)
    assert admin.is_active and admins.has_permission(db, admin, "admins.manage")
    row = audit.list_logs(db)[0]
    assert row.result == "refused" and row.target_admin_id == admin.id
    assert row.action in {"admin.disable", "admin.revoke", "admin.set_permissions"}


def test_admin_lifecycle_permissions_and_sessions(db):
    admin = owner(db)
    other = owner(db, "second")
    workflow.admin_disable(db, admin.id, actor=ACTOR)
    assert not admin.is_active and not admins.has_permission(db, admin, "accounts.read")
    workflow.admin_enable(db, admin.id, actor=ACTOR)
    workflow.admin_set_permissions(db, admin.id, PRESETS["viewer"], actor=ACTOR)
    workflow.admin_grant(db, admin.id, ["accounts.manage"], actor=ACTOR)
    workflow.admin_revoke(db, admin.id, ["accounts.read"], actor=ACTOR)
    assert admins.permissions_for(db, admin) == PRESETS["viewer"] - {"accounts.read"} | {"accounts.manage"}
    assert {row["username"] for row in admins.list_admins(db)} == {"owner", "second"}
    assert all("password_hash" not in row and "totp_secret_encrypted" not in row for row in admins.list_admins(db))
    secret = admins.provisioning(other)["manual_entry_key"]
    assert admins.confirm_totp(db, other, pyotp.TOTP(secret).now())
    cookie = admins.create_session(db, other, ip="127.0.0.1", user_agent="test")
    row = admins.find_session(db, cookie)
    assert row.id == hashlib.sha256(cookie.encode()).hexdigest() and cookie not in str(row.__dict__)
    admins.touch_session(db, row, stepped_up=True)
    assert row.stepped_up_at and row.ip == "127.0.0.1"
    admins.revoke_session(db, row)
    assert admins.find_session(db, cookie) is None
    cookie = admins.create_session(db, other)
    admins.set_password(db, other, PASSWORD + "new")
    assert admins.find_session(db, cookie) is None and admins.verify_password(db, other, PASSWORD + "new")
    cookie = admins.create_session(db, other)
    temporary = workflow.admin_reset_mfa(db, other.id, actor=ACTOR)
    assert other.must_change_password and not other.mfa_enabled and other.totp_secret_encrypted is None
    assert other.last_totp_step is None and verify_password(temporary, other.password_hash)
    assert admins.find_session(db, cookie) is None
    admins.set_password(db, other, PASSWORD + "again")
    assert admins.start_totp_setup(db, other)["manual_entry_key"]
    assert temporary not in json.dumps([row.detail for row in audit.list_logs(db)])


@pytest.mark.parametrize("kind", ["create", "grant", "revoke", "set", "has"])
def test_unknown_permissions_rejected_at_every_boundary(db, kind):
    admin = owner(db)
    with pytest.raises(Invalid):
        if kind == "create":
            admins.create(db, "bad", PASSWORD, ACTOR, permissions=["typo"])
        elif kind == "has":
            admins.has_permission(db, admin, "typo")
        else:
            function = {"grant": admins.grant, "revoke": admins.revoke, "set": admins.set_permissions}[kind]
            function(db, admin, ["typo"], ACTOR)
    assert admins.permissions_for(db, admin) == ALL_PERMISSIONS


def test_admin_password_minimum_totp_confirmation_and_replay(db):
    with pytest.raises(Invalid):
        admins.create(db, "short", "a" * 11, ACTOR)
    admin, setup = admins.create(db, "UPPER", "a" * 12, ACTOR, permissions=PRESETS["owner"])
    assert admin.username == "upper" and not admin.mfa_enabled
    assert security.decrypt_key(admin.totp_secret_encrypted) == setup["manual_entry_key"]
    with pytest.raises(Refused):
        admins.create_session(db, admin)
    totp = pyotp.TOTP(setup["manual_entry_key"])
    assert not admins.verify_totp(db, admin, totp.now())
    assert admins.confirm_totp(db, admin, totp.now())
    assert admin.mfa_enabled and admin.last_totp_step is not None
    assert not admins.confirm_totp(db, admin, totp.now())
    assert not admins.verify_totp(db, admin, totp.now())
    assert admins.verify_totp(db, admin, totp.generate_otp(admin.last_totp_step + 1))
    assert admin.last_login_at and admin.failed_login_count == 0
    assert not admins.verify_totp(db, admin, "１２３４５６")


def test_admin_conditional_totp_update_rejects_stale_objects(db):
    admin = owner(db)
    code = pyotp.TOTP(admins.provisioning(admin)["manual_entry_key"]).now()
    with Session(db.bind, autoflush=False) as other:
        stale = other.get(models.AdminUser, admin.id)
        assert stale.last_totp_step is None
        assert admins.confirm_totp(db, admin, code)
        assert not admins.confirm_totp(other, stale, code)
        other.refresh(stale)
        assert stale.mfa_enabled


def test_admin_lockout_uses_settings_for_password_and_totp(db):
    admin = owner(db)
    settings.set(db, "login_lockout_threshold", 3, ACTOR)
    settings.set(db, "login_lockout_minutes", 2, ACTOR)
    before = datetime.utcnow()
    for i in range(3):
        assert not admins.verify_password(db, admin, "wrong")
        assert admins.is_locked(admin) == (i == 2)
    assert before + timedelta(minutes=2) <= admin.locked_until <= datetime.utcnow() + timedelta(minutes=2)
    assert not admins.verify_password(db, admin, PASSWORD)
    admin.locked_until = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert admins.verify_password(db, admin, PASSWORD)
    assert not admins.confirm_totp(db, admin, "bad")
    assert admin.failed_login_count == 1 and admin.locked_until is None
    for _ in range(2):
        assert not admins.confirm_totp(db, admin, "bad")
    assert admins.is_locked(admin)


def test_audit_filters_pagination_and_secret_key_rejection(db):
    now = datetime.utcnow()
    audit.record(db, ACTOR, "client.suspend", target_client_id=1, commit=True)
    audit.record(db, "cli:other", "admin.enable", target_admin_id=2, result="refused", commit=True)
    assert len(audit.list_logs(db, actor=ACTOR, action_prefix="client.", target_client_id=1, start_at=now,
                               end_at=datetime.utcnow(), limit=10)) == 1
    assert len(audit.list_logs(db, target_admin_id=2)) == 1
    assert len(audit.list_logs(db, limit=1, offset=1)) == 1
    assert audit.list_logs(db, action_prefix="client.%") == []
    with pytest.raises(Invalid):
        audit.record(db, ACTOR, "test", detail={"nested": [{"totp_secret": "never"}]})
    with pytest.raises(Invalid):
        audit.record(db, ACTOR, "test", result="unknown")


def test_admin_secret_reencrypted_and_dry_run_preserves_store(db, monkeypatch):
    from cryptography.fernet import Fernet
    admin = owner(db)
    secret = admins.provisioning(admin)["manual_entry_key"]
    previous = admin.totp_secret_encrypted
    new_key = Fernet.generate_key().decode()
    old_key = security.ENCRYPTION_KEY
    monkeypatch.setattr(security, "fernet", security.build_fernet([new_key, old_key]))
    assert reencrypt(db, apply=False) == {"rotated": 1, "unreadable": 0}
    db.refresh(admin)
    assert admin.totp_secret_encrypted == previous
    assert reencrypt(db, apply=True) == {"rotated": 1, "unreadable": 0}
    assert admin.totp_secret_encrypted != previous
    monkeypatch.setattr(security, "fernet", security.build_fernet([new_key]))
    assert security.decrypt_key(admin.totp_secret_encrypted) == secret


def test_duplicate_client_creation_is_audited_without_credentials(db):
    from app.domain.errors import Conflict
    workflow.client_create(db, "same", "One", actor=ACTOR)
    with pytest.raises(Conflict):
        workflow.client_create(db, "same", "Two", actor=ACTOR)
    assert db.query(models.Client).count() == 1
    assert audit.list_logs(db)[0].action == "client.create" and audit.list_logs(db)[0].result == "failed"
    assert audit.list_logs(db)[0].detail == {}


def test_client_commit_false_and_settings_remain_rollbackable(db):
    client, _ = workflow.client_create(db, "test", "Test", actor=ACTOR)
    old_hash = client.password_hash
    clients.suspend(db, client, "reason", commit=False)
    clients.reset_password(db, client, commit=False)
    settings.set(db, "registration_mode", "closed", ACTOR, commit=False)
    db.rollback()
    db.refresh(client)
    assert client.is_active and client.suspended_reason is None and client.password_hash == old_hash
    assert settings.get(db, "registration_mode") == "open"


def test_admin_session_expiry_disablement_and_token_cutoff(db):
    admin = owner(db)
    owner(db, "other")
    assert admins.confirm_totp(db, admin, pyotp.TOTP(admins.provisioning(admin)["manual_entry_key"]).now())
    expired = admins.create_session(db, admin, expires_at=datetime.utcnow() - timedelta(seconds=1))
    assert admins.find_session(db, expired) is None
    assert admins.find_session(db, "unknown") is None
    cookie = admins.create_session(db, admin)
    workflow.admin_disable(db, admin.id, actor=ACTOR)
    assert admins.find_session(db, cookie) is None
    workflow.admin_enable(db, admin.id, actor=ACTOR)
    assert admins.find_session(db, cookie) is None  # Enabling cannot revive revoked sessions.
    cookie = admins.create_session(db, admin)
    admin.tokens_valid_after = datetime.utcnow() + timedelta(seconds=1)
    db.commit()
    assert admins.find_session(db, cookie) is None


def test_actor_admin_id_is_attached_to_audit(db):
    admin = owner(db)
    client, _ = workflow.client_create(db, "test", "Test", actor=f"admin:{admin.id}", admin_user_id=admin.id)
    row = audit.list_logs(db)[0]
    assert row.admin_user_id == admin.id and row.actor == f"admin:{admin.id}" and row.target_client_id == client.id
