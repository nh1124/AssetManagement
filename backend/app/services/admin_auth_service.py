"""Owns administrator credentials, capabilities and opaque browser sessions."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

import pyotp
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from .. import models
from ..domain.admin_permissions import ADMINS_MANAGE, validate_permissions
from ..domain.errors import Conflict, Invalid, NotFound, Refused
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


def create_session(db: Session, admin, *, expires_at=None, ip=None, user_agent=None, commit: bool = True) -> str:
    if not admin.is_active or not admin.mfa_enabled or admin.must_change_password or is_locked(admin):
        raise Refused("Administrator sign-in is incomplete.", ja="管理者のサインインが完了していません。")
    now = datetime.utcnow()
    raw = secrets.token_urlsafe(32)
    db.add(models.AdminSession(id=hashlib.sha256(raw.encode()).hexdigest(), admin_user_id=admin.id,
                              created_at=now, last_seen_at=now, expires_at=expires_at or now + timedelta(hours=8),
                              ip=ip, user_agent=user_agent))
    _save(db, commit)
    return raw


def find_session(db: Session, raw_cookie: str):
    row = db.get(models.AdminSession, hashlib.sha256(raw_cookie.encode()).hexdigest())
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.utcnow():
        return None
    admin = get_by_id(db, row.admin_user_id)
    if (not admin.is_active or not admin.mfa_enabled or admin.must_change_password
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
