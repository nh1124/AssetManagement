"""TOTP matching shared by the two independent identity stores."""
from datetime import datetime, timezone
import secrets

import pyotp


def matching_totp_step(secret: str | None, code: str, last_step: int | None = None, *, now: datetime | None = None) -> int | None:
    if not secret:
        return None
    totp = pyotp.TOTP(secret)
    current_step = totp.timecode(now or datetime.now(timezone.utc))
    candidate = (code or "").strip().replace(" ", "")
    if len(candidate) != totp.digits or not candidate.isascii() or not candidate.isdigit():
        return None
    for offset in (-1, 0, 1):
        step = current_step + offset
        if (last_step is None or step > last_step) and secrets.compare_digest(totp.generate_otp(step), candidate):
            return step
    return None

