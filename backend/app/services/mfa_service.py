from __future__ import annotations

from datetime import datetime
import secrets
import string

import pyotp
from sqlalchemy.orm import Session

from .. import models
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
    secret = pyotp.random_base32()
    setting = get_mfa_setting(db, client, create=True)
    setting.totp_secret_encrypted = encrypt_key(secret)
    setting.enabled = False
    setting.enabled_at = None
    setting.last_verified_at = None
    db.commit()
    db.refresh(setting)

    label = client.username or client.email or client.name or f"client-{client.id}"
    otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name="Finance IDE")
    return {
        "otpauth_uri": otpauth_uri,
        "manual_entry_key": secret,
    }


def verify_totp_setup(db: Session, client: models.Client, code: str) -> list[str]:
    setting = get_mfa_setting(db, client)
    if not setting or not setting.totp_secret_encrypted:
        raise ValueError("MFA setup has not been started")

    if not verify_totp_code(setting, code):
        raise ValueError("Invalid MFA code")

    now = datetime.utcnow()
    setting.enabled = True
    setting.enabled_at = now
    setting.last_verified_at = now
    recovery_codes = regenerate_recovery_codes(db, client, commit=False)
    db.commit()
    return recovery_codes


def disable_mfa(db: Session, client: models.Client) -> None:
    setting = get_mfa_setting(db, client)
    if setting:
        setting.enabled = False
        setting.totp_secret_encrypted = None
        setting.enabled_at = None
        setting.last_verified_at = None

    db.query(models.ClientRecoveryCode).filter(models.ClientRecoveryCode.client_id == client.id).delete()
    db.commit()


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


def verify_reauth_factor(
    db: Session,
    client: models.Client,
    current_password: str | None = None,
    code: str | None = None,
    recovery_code: str | None = None,
) -> bool:
    if current_password and verify_password(current_password, client.password_hash or ""):
        return True
    return verify_mfa_factor(db, client, code=code, recovery_code=recovery_code)


def _new_recovery_code() -> str:
    left = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(4))
    return f"{left}-{right}"


def _normalize_recovery_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")
