from __future__ import annotations

from datetime import datetime
import secrets
import string

import pyotp
from sqlalchemy.orm import Session

from .. import models
from ..domain.messages import Message
from ..security import decrypt_key, encrypt_key
from ..utils.password import hash_password, verify_password

RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_ALPHABET = string.ascii_uppercase + string.digits


def get_mfa_setting(db: Session, client: models.Client, create: bool = False) -> models.ClientMfaSetting | None:
    setting = db.query(models.ClientMfaSetting).filter(models.ClientMfaSetting.client_id == client.id).first()
    if setting or not create:
        return setting

    setting = models.ClientMfaSetting(client_id=client.id, enabled=False)
    db.add(setting)
    db.flush()
    return setting


def mfa_enabled(db: Session, client_id: int) -> bool:
    return db.query(models.ClientMfaSetting.id).filter(
        models.ClientMfaSetting.client_id == client_id,
        models.ClientMfaSetting.enabled.is_(True),
    ).first() is not None


def mfa_status(db: Session, client: models.Client) -> dict:
    setting = get_mfa_setting(db, client)
    remaining = db.query(models.ClientRecoveryCode).filter(
        models.ClientRecoveryCode.client_id == client.id,
        models.ClientRecoveryCode.used_at.is_(None),
    ).count()
    return {
        "enabled": bool(setting and setting.enabled),
        "enabled_at": setting.enabled_at if setting else None,
        "last_verified_at": setting.last_verified_at if setting else None,
        "recovery_codes_remaining": remaining,
    }


def start_totp_setup(db: Session, client: models.Client) -> dict:
    setting = get_mfa_setting(db, client, create=True)
    if setting.enabled:
        raise ValueError(Message("MFA is already enabled", ja="MFAはすでに有効です。"))
    secret = pyotp.random_base32()
    setting.totp_secret_encrypted = encrypt_key(secret)
    setting.enabled = False
    setting.enabled_at = None
    setting.last_verified_at = None
    db.commit()
    db.refresh(setting)

    return _provisioning(client, secret)


def _provisioning(client: models.Client, secret: str) -> dict:
    label = client.username or client.email or client.name or f"client-{client.id}"
    otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name="Finance IDE")
    return {
        "otpauth_uri": otpauth_uri,
        "manual_entry_key": secret,
    }


def verify_totp_setup(db: Session, client: models.Client, code: str) -> list[str]:
    setting = get_mfa_setting(db, client)
    if not setting or setting.enabled or not setting.totp_secret_encrypted:
        raise ValueError(Message("MFA setup has not been started", ja="MFAの設定が始まっていません。最初からやり直してください。"))

    if not verify_totp_code(setting, code):
        raise ValueError(Message("Invalid MFA code", ja="認証コードが正しくありません。"))

    now = datetime.utcnow()
    setting.enabled = True
    setting.enabled_at = now
    setting.last_verified_at = now
    recovery_codes = regenerate_recovery_codes(db, client, commit=False)
    db.commit()
    return recovery_codes


def regenerate_recovery_codes(db: Session, client: models.Client, commit: bool = True) -> list[str]:
    db.query(models.ClientRecoveryCode).filter(models.ClientRecoveryCode.client_id == client.id).delete()
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        db.add(models.ClientRecoveryCode(client_id=client.id, code_hash=hash_password(_normalize_recovery_code(code))))
    if commit:
        db.commit()
    return codes


def verify_totp_code(setting: models.ClientMfaSetting, code: str) -> bool:
    secret = decrypt_key(setting.totp_secret_encrypted or "")
    if not secret:
        return False
    return pyotp.TOTP(secret).verify((code or "").strip().replace(" ", ""), valid_window=1)


def verify_mfa_factor(db: Session, client: models.Client, code: str | None = None, recovery_code: str | None = None) -> bool:
    setting = get_mfa_setting(db, client)
    if not setting or not setting.enabled:
        return False

    if code and verify_totp_code(setting, code):
        setting.last_verified_at = datetime.utcnow()
        db.commit()
        return True

    if recovery_code and consume_recovery_code(db, client, recovery_code):
        setting.last_verified_at = datetime.utcnow()
        db.commit()
        return True

    return False


def consume_recovery_code(db: Session, client: models.Client, code: str) -> bool:
    normalized = _normalize_recovery_code(code)
    if not normalized:
        return False

    rows = db.query(models.ClientRecoveryCode).filter(
        models.ClientRecoveryCode.client_id == client.id,
        models.ClientRecoveryCode.used_at.is_(None),
    ).all()
    for row in rows:
        if verify_password(normalized, row.code_hash):
            row.used_at = datetime.utcnow()
            return True
    return False


def _new_recovery_code() -> str:
    left = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4))
    return f"{left}-{right}"


def _normalize_recovery_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def start_totp_replacement(db: Session, client: models.Client) -> dict:
    setting = get_mfa_setting(db, client)
    if not setting or not setting.enabled:
        raise ValueError(Message("MFA is not enabled", ja="MFAは有効になっていません。"))
    secret = pyotp.random_base32()
    setting.pending_totp_secret_encrypted = encrypt_key(secret)
    db.commit()
    return _provisioning(client, secret)


def verify_totp_replacement(db: Session, client: models.Client, code: str) -> list[str]:
    setting = get_mfa_setting(db, client)
    secret = decrypt_key(setting.pending_totp_secret_encrypted or "") if setting else None
    if not secret or not pyotp.TOTP(secret).verify((code or "").strip().replace(" ", ""), valid_window=1):
        raise ValueError(Message("Invalid MFA code", ja="認証コードが正しくありません。"))
    setting.totp_secret_encrypted = setting.pending_totp_secret_encrypted
    setting.pending_totp_secret_encrypted = None
    setting.last_verified_at = datetime.utcnow()
    # The caller commits the swap, new recovery codes and token revocation together.
    return regenerate_recovery_codes(db, client, commit=False)


def ensure_development_mfa(db: Session, client: models.Client) -> None:
    from ..config import DEV_TOTP_SECRET

    setting = get_mfa_setting(db, client, create=True)
    setting.totp_secret_encrypted = encrypt_key(DEV_TOTP_SECRET)
    setting.pending_totp_secret_encrypted = None
    setting.enabled = True
    setting.enabled_at = setting.enabled_at or datetime.utcnow()
    if not db.query(models.ClientRecoveryCode.id).filter(
        models.ClientRecoveryCode.client_id == client.id,
        models.ClientRecoveryCode.used_at.is_(None),
    ).first():
        regenerate_recovery_codes(db, client, commit=False)
    db.commit()


def ensure_no_development_totp(db: Session) -> None:
    from ..config import DEV_TOTP_SECRET

    settings = db.query(models.ClientMfaSetting).join(models.Client).filter(
        models.Client.is_active.is_(True),
    ).all()
    if any(decrypt_key(setting.totp_secret_encrypted or "") == DEV_TOTP_SECRET for setting in settings):
        raise RuntimeError("Invalid production configuration: development TOTP secret is still active")
