"""Re-encrypt every stored secret under the current ENCRYPTION_KEY.

Second step of a key rotation. The first is configuration: the new key becomes
ENCRYPTION_KEY and the old one moves to ENCRYPTION_KEY_PREVIOUS, after which
both can decrypt but only the new one encrypts. This rewrites what is already
stored, so the old key can then be removed.

Dry-run by default. Run inside the backend container:

    python -m app.maintenance.reencrypt_secrets
    python -m app.maintenance.reencrypt_secrets --apply

The stored secrets are the TOTP secrets in client_mfa_settings (the AI
provider keys that used to live in clients.ai_config are gone). A value no
configured key can read is counted as unreadable and left untouched.
"""
from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from .. import models, security


def reencrypt(db: Session, *, apply: bool) -> dict[str, int]:
    counts = {"rotated": 0, "unreadable": 0}

    for setting in db.query(models.ClientMfaSetting).all():
        for field in ("totp_secret_encrypted", "pending_totp_secret_encrypted"):
            value = getattr(setting, field)
            if value is None:
                continue
            fresh = security.rotate_token(value)
            counts["rotated" if fresh else "unreadable"] += 1
            if fresh:
                setattr(setting, field, fresh)

    if apply:
        db.commit()
    else:
        db.rollback()
    return counts


def main() -> int:
    from ..database import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="persist the re-encrypted values")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        counts = reencrypt(db, apply=args.apply)
    finally:
        db.close()
    mode = "applied" if args.apply else "dry-run"
    print(f"{mode}: rotated={counts['rotated']} unreadable={counts['unreadable']}")
    # Unreadable values mean a key is missing from ENCRYPTION_KEY_PREVIOUS;
    # dropping the old key now would lose them.
    return 1 if counts["unreadable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
