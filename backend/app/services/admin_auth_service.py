"""Owns administrator credentials, capabilities and opaque browser sessions."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

import pyotp
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from ..config import settings
from .. import models
from ..domain.admin_permissions import ADMINS_MANAGE, validate_permissions
from ..domain.errors import Conflict, Invalid, NotFound, Refused
from ..domain.messages import Message
from ..security import decrypt_key, encrypt_key
from ..utils.password import hash_password, verify_password as check_password
from ..utils.temporary_password import temporary_password
from ..utils.totp import matching_totp_step
from . import system_settings_service


def _save(db, commit):
    db.commit() if commit else db.flush()


def get_by_username(db: Session, username: str):
    return db.query(models.AdminUser).filter_by(username=username.strip().lower()).first()


def get_by_id(db: Session, admin_id: int):
    admin = db.get(models.AdminUser, admin_id)
    if admin is None:
        raise NotFound("Administrator not found.", ja="管理者が見つかりません。")
    return admin


def _validate_password(password):
    if len(password.encode("utf-8")) > 72:
        raise Invalid("Administrator passwords must fit within 72 UTF-8 bytes.", ja="管理者パスワードはUTF-8で72バイト以内にしてください。")
    if len(password) < 12:
        raise Invalid("Administrator passwords need at least 12 characters.", ja="管理者パスワードは12文字以上にしてください。")


def provisioning(admin) -> dict:
    secret = decrypt_key(admin.totp_secret_encrypted or "")
    if not secret:
        raise Refused("MFA setup has not been started.", ja="MFAの設定が始まっていません。")
    return {"manual_entry_key": secret,
            "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=admin.username, issuer_name="Finance IDE Admin")}


def create(db: Session, username: str, password: str, actor: str, *, permissions=(), commit: bool = True):
    _validate_password(password)
    permissions = validate_permissions(permissions)
    username = username.strip().lower()
    if not username:
        raise Invalid("Username is required.", ja="ユーザー名を入力してください。")
    if get_by_username(db, username):
        raise Conflict("Username already taken.", ja="このユーザー名は使われています。")
    admin = models.AdminUser(username=username, password_hash=hash_password(password),
                             totp_secret_encrypted=encrypt_key(pyotp.random_base32()), created_by=actor)
    db.add(admin)
    db.flush()
    for permission in sorted(permissions):
        db.add(models.AdminUserPermission(admin_user_id=admin.id, permission=permission, granted_by=actor))
    _save(db, commit)
    return admin, provisioning(admin)


def is_locked(admin) -> bool:
    return admin.locked_until is not None and admin.locked_until > datetime.utcnow()


def _failure(db, admin, commit):
    now = datetime.utcnow()
    threshold = system_settings_service.get(db, "login_lockout_threshold")
    minutes = system_settings_service.get(db, "login_lockout_minutes")
    count = case((models.AdminUser.locked_until <= now, 1), else_=models.AdminUser.failed_login_count + 1)
    db.query(models.AdminUser).filter_by(id=admin.id).update({
        models.AdminUser.failed_login_count: count,
        models.AdminUser.locked_until: case((count >= threshold, now + timedelta(minutes=minutes)), else_=None),
    }, synchronize_session=False)
    _save(db, commit)
    db.refresh(admin)


def verify_password(db: Session, admin, password: str, *, commit: bool = True) -> bool:
    if not admin.is_active or is_locked(admin):
        return False
    if not check_password(password, admin.password_hash):
        _failure(db, admin, commit)
        return False
    # The failure counter is cleared only after the second factor succeeds.
    return True


def _consume_totp(db, admin, code) -> bool:
    step = matching_totp_step(decrypt_key(admin.totp_secret_encrypted or ""), code, admin.last_totp_step, now=datetime.now(timezone.utc))
    if step is None:
        return False
    consumed = db.query(models.AdminUser).filter(
        models.AdminUser.id == admin.id,
        models.AdminUser.totp_secret_encrypted == admin.totp_secret_encrypted,
        or_(models.AdminUser.last_totp_step.is_(None), models.AdminUser.last_totp_step < step),
    ).update({models.AdminUser.last_totp_step: step}, synchronize_session=False)
    db.refresh(admin)
    return bool(consumed)


def confirm_totp(db: Session, admin, code: str, *, commit: bool = True) -> bool:
    if not admin.is_active or admin.mfa_enabled or is_locked(admin):
        return False
    if not _consume_totp(db, admin, code):
        _failure(db, admin, commit)
        return False
    admin.mfa_enabled, admin.failed_login_count, admin.locked_until = True, 0, None
    _save(db, commit)
    return True


def verify_totp(db: Session, admin, code: str, *, commit: bool = True) -> bool:
    if not admin.is_active or not admin.mfa_enabled or is_locked(admin):
        return False
    if not _consume_totp(db, admin, code):
        _failure(db, admin, commit)
        return False
    admin.failed_login_count, admin.locked_until, admin.last_login_at = 0, None, datetime.utcnow()
    _save(db, commit)
    return True


def _revoke_sessions(db, admin):
    now = datetime.utcnow()
    admin.tokens_valid_after = now
    db.query(models.AdminSession).filter_by(admin_user_id=admin.id, revoked_at=None).update(
        {models.AdminSession.revoked_at: now}, synchronize_session="fetch")


def set_password(db: Session, admin, password: str, *, commit: bool = True):
    _validate_password(password)
    if check_password(password, admin.password_hash):
        raise Invalid("Choose a different password.", ja="異なるパスワードを選んでください。")
    admin.password_hash, admin.must_change_password = hash_password(password), False
    _revoke_sessions(db, admin)
    _save(db, commit)
    return admin


def _lock_administrators(db):
    # All capability/active changes take the same row locks in id order. Two
    # concurrent owners cannot both decide the other owner will remain active.
    db.query(models.AdminUser).order_by(models.AdminUser.id).populate_existing().with_for_update().all()


def _ensure_manager_remains(db, admin, *, active, permissions):
    if active and ADMINS_MANAGE in permissions:
        return
    other = db.query(models.AdminUser.id).join(models.AdminUserPermission).filter(
        models.AdminUser.id != admin.id, models.AdminUser.is_active.is_(True),
        models.AdminUserPermission.permission == ADMINS_MANAGE,
    ).first()
    if other is None:
        raise Refused("At least one active administrator must retain admins.manage.",
                      ja="admins.manage を持つ有効な管理者を最低1人残してください。")


def permissions_for(db, admin) -> frozenset[str]:
    return validate_permissions(row[0] for row in db.query(models.AdminUserPermission.permission).filter_by(admin_user_id=admin.id))


def disable(db: Session, admin, *, commit: bool = True):
    _lock_administrators(db)
    _ensure_manager_remains(db, admin, active=False, permissions=permissions_for(db, admin))
    admin.is_active = False
    _revoke_sessions(db, admin)
    _save(db, commit)
    return admin


def enable(db: Session, admin, *, commit: bool = True):
    _lock_administrators(db)
    admin.is_active = True
    _save(db, commit)
    return admin


def reset_mfa(db: Session, admin, *, commit: bool = True) -> str:
    password = temporary_password()
    admin.totp_secret_encrypted, admin.last_totp_step, admin.mfa_enabled = None, None, False
    admin.password_hash, admin.must_change_password = hash_password(password), True
    _revoke_sessions(db, admin)
    _save(db, commit)
    return password


def start_totp_setup(db: Session, admin, *, commit: bool = True):
    if admin.mfa_enabled:
        raise Refused("MFA is already enabled.", ja="MFAはすでに有効です。")
    admin.totp_secret_encrypted = encrypt_key(pyotp.random_base32())
    admin.last_totp_step = None
    _save(db, commit)
    return provisioning(admin)


def set_permissions(db: Session, admin, permissions, actor: str, *, commit: bool = True):
    permissions = validate_permissions(permissions)
    _lock_administrators(db)
    _ensure_manager_remains(db, admin, active=admin.is_active, permissions=permissions)
    existing = {row.permission: row for row in db.query(models.AdminUserPermission).filter_by(admin_user_id=admin.id)}
    for permission, row in existing.items():
        if permission not in permissions:
            db.delete(row)
    for permission in sorted(permissions - existing.keys()):
        db.add(models.AdminUserPermission(admin_user_id=admin.id, permission=permission, granted_by=actor))
    _save(db, commit)
    return admin


def grant(db: Session, admin, permissions, actor: str, *, commit: bool = True):
    values = validate_permissions(permissions)
    _lock_administrators(db)
    return set_permissions(db, admin, permissions_for(db, admin) | values, actor, commit=commit)


def revoke(db: Session, admin, permissions, actor: str, *, commit: bool = True):
    values = validate_permissions(permissions)
    _lock_administrators(db)
    return set_permissions(db, admin, permissions_for(db, admin) - values, actor, commit=commit)


def has_permission(db: Session, admin, permission: str) -> bool:
    validate_permissions([permission])
    return bool(admin.is_active and permission in permissions_for(db, admin))


def list_admins(db: Session) -> list[dict]:
    admins = db.query(models.AdminUser).order_by(models.AdminUser.id).all()
    permissions = {}
    for row in db.query(models.AdminUserPermission).order_by(models.AdminUserPermission.permission):
        validate_permissions([row.permission])
        permissions.setdefault(row.admin_user_id, []).append(row.permission)
    return [{**{key: getattr(admin, key) for key in (
        "id", "username", "is_active", "mfa_enabled", "must_change_password", "locked_until", "last_login_at", "created_at", "created_by")},
        "permissions": permissions.get(admin.id, [])} for admin in admins]


def create_session(db: Session, admin, *, expires_at=None, ip=None, user_agent=None, stage=None, stepped_up=False, config=None, commit: bool = True) -> str:
    config = config or settings
    if stage not in {None, "password_change", "mfa_setup", "mfa"}:
        raise Invalid("Invalid session stage.", ja="セッションの段階が正しくありません。")
    if not admin.is_active or is_locked(admin) or (stage is None and (not admin.mfa_enabled or admin.must_change_password)):
        raise Refused("Administrator sign-in is incomplete.", ja="管理者のサインインが完了していません。")
    now = datetime.utcnow()
    raw = secrets.token_urlsafe(32)
    db.add(models.AdminSession(id=hashlib.sha256(raw.encode()).hexdigest(), admin_user_id=admin.id,
                              created_at=now, last_seen_at=now, expires_at=expires_at or now + (timedelta(minutes=10) if stage else timedelta(hours=config.admin_session_max_hours)),
                              stage=stage, stepped_up_at=now if stepped_up else None,
                              ip=ip, user_agent=user_agent))
    _save(db, commit)
    return raw


def find_session(db: Session, raw_cookie: str, *, config=None):
    config = config or settings
    row = db.get(models.AdminSession, hashlib.sha256(raw_cookie.encode()).hexdigest())
    now = datetime.utcnow()
    if (row is None or row.revoked_at is not None or row.expires_at <= now
            or row.last_seen_at <= now - timedelta(minutes=config.admin_session_idle_minutes)):
        return None
    admin = get_by_id(db, row.admin_user_id)
    if (not admin.is_active or (row.stage is None and (not admin.mfa_enabled or admin.must_change_password))
            or (admin.tokens_valid_after is not None and row.created_at < admin.tokens_valid_after)):
        return None
    return row


def touch_session(db: Session, session, *, stepped_up: bool = False, commit: bool = True):
    session.last_seen_at = datetime.utcnow()
    if stepped_up:
        session.stepped_up_at = session.last_seen_at
    _save(db, commit)
    return session


def revoke_session(db: Session, session, *, commit: bool = True):
    session.revoked_at = datetime.utcnow()
    _save(db, commit)


class SessionStageRefused(Refused):
    def __init__(self, row, required_stage):
        super().__init__(Message("Administrator authentication required.", ja="管理者としてサインインしてください。"), status_code=401)
        self.admin_user_id = row.admin_user_id
        self.stage = row.stage
        self.required_stage = required_stage


def session_admin(db, raw_cookie, *, stage=None, any_stage=False, config=None):
    row = find_session(db, raw_cookie or "", config=config)
    if row is None:
        raise Refused("Administrator authentication required.", ja="管理者としてサインインしてください。", status_code=401)
    if not any_stage and row.stage != stage:
        raise SessionStageRefused(row, stage)
    touch_session(db, row)
    return get_by_id(db, row.admin_user_id), row


def session_summary(row):
    return {key: getattr(row, key) for key in ("id", "created_at", "last_seen_at", "expires_at", "stepped_up_at", "stage")}


def own_sessions(db, admin, *, config=None):
    config = config or settings
    now = datetime.utcnow()
    return [session_summary(row) for row in db.query(models.AdminSession).filter(
        models.AdminSession.admin_user_id == admin.id, models.AdminSession.revoked_at.is_(None),
        models.AdminSession.expires_at > now,
        models.AdminSession.last_seen_at > now - timedelta(minutes=config.admin_session_idle_minutes),
    ).order_by(models.AdminSession.created_at.desc())]


def revoke_own_session(db, admin, session_id, *, commit=True):
    row = db.query(models.AdminSession).filter_by(id=session_id, admin_user_id=admin.id).first()
    if row is None:
        raise NotFound("Session not found.", ja="セッションが見つかりません。")
    revoke_session(db, row, commit=commit)


def _check_login_state(admin):
    if admin is None or not admin.is_active:
        raise Refused("Invalid administrator credentials.", ja="管理者の認証情報が正しくありません。", status_code=401)
    if is_locked(admin):
        raise Refused("Administrator is locked.", ja="管理者がロックされています。", status_code=429)


def _code(db, admin, code, *, setup=False):
    _check_login_state(admin)
    valid = confirm_totp(db, admin, code, commit=False) if setup else verify_totp(db, admin, code, commit=False)
    if not valid:
        raise Refused("Invalid authentication code.", ja="認証コードが正しくありません。", status_code=401)


def sign_in(db, username, password, code=None, *, ip=None, user_agent=None, config=None):
    admin = get_by_username(db, username)
    _check_login_state(admin)
    if not verify_password(db, admin, password, commit=False):
        raise Refused("Invalid administrator credentials.", ja="管理者の認証情報が正しくありません。", status_code=401)
    if admin.must_change_password:
        stage = "password_change"
    elif not admin.mfa_enabled:
        stage = "mfa_setup"
    elif code is None:
        stage = "mfa"
    else:
        _code(db, admin, code)
        stage = None
    raw = create_session(db, admin, stage=stage, stepped_up=stage is None, ip=ip, user_agent=user_agent, config=config, commit=False)
    return admin, raw, stage


def transition(db, admin, row, endpoint, *, new_password=None, code=None, ip=None, user_agent=None, config=None):
    expected = {"password": "password_change", "code": "mfa", "setup_start": "mfa_setup", "setup_verify": "mfa_setup"}
    if row.stage != expected[endpoint]:
        raise Refused("Invalid session stage.", ja="セッションの段階が正しくありません。", status_code=401)
    _check_login_state(admin)
    extra = {}
    if endpoint == "password":
        set_password(db, admin, new_password, commit=False)
        stage = "mfa" if admin.mfa_enabled else "mfa_setup"
    elif endpoint == "setup_start":
        extra = start_totp_setup(db, admin, commit=False)
        stage = "mfa_setup"
    else:
        _code(db, admin, code, setup=endpoint == "setup_verify")
        stage = None
    revoke_session(db, row, commit=False)
    raw = create_session(db, admin, stage=stage, stepped_up=stage is None, ip=ip, user_agent=user_agent, config=config, commit=False)
    return admin, raw, stage, extra


def step_up(db, admin, row, code):
    _code(db, admin, code)
    touch_session(db, row, stepped_up=True, commit=False)


def change_own_password(db, admin, row, current_password, new_password):
    _check_login_state(admin)
    if not verify_password(db, admin, current_password, commit=False):
        raise Refused("Invalid administrator credentials.", ja="管理者の認証情報が正しくありません。", status_code=401)
    set_password(db, admin, new_password, commit=False)
    # Preserve this session, including its original absolute expiry.
    row.revoked_at = None
    admin.tokens_valid_after = row.created_at
    db.flush()


def create_web_admin(db, username, permissions, actor):
    password = temporary_password()
    admin, _ = create(db, username, password, actor, permissions=permissions, commit=False)
    admin.must_change_password = True
    admin.totp_secret_encrypted = None
    db.flush()
    return admin, password


def update_admin(db, admin_id, *, is_active=None, permissions=None, actor):
    admin = get_by_id(db, admin_id)
    if permissions is not None:
        set_permissions(db, admin, permissions, actor, commit=False)
    if is_active is not None:
        (enable if is_active else disable)(db, admin, commit=False)
    return admin
