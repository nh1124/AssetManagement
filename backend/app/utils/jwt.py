from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Optional
from jose import jwt, JWTError
from ..config import settings

def create_access_token(
    user_id: str, 
    username: str, 
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token. Pattern from VisionArk."""
    return create_typed_token(
        user_id=user_id,
        username=username,
        token_type="access",
        expires_delta=expires_delta,
    )


def create_typed_token(
    user_id: str,
    username: str,
    token_type: str,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict] = None,
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expire_minutes)

    now = datetime.now(timezone.utc)
    expire = now + expires_delta

    payload = {
        # Extra claims first, so none of them can replace who the token is for or when it ends.
        **(extra_claims or {}),
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "iat": now,
        "iat_ms": now.timestamp() * 1000,
        "type": token_type,
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def token_is_current(payload: dict, cutoff: Optional[datetime], *, claim: str = "iat_ms", required: bool = False) -> bool:
    """Compare UTC issue times without discarding subsecond revocation precision."""
    if cutoff is None and not required:
        return True
    issued = payload.get(claim)
    if isinstance(issued, bool) or not isinstance(issued, (int, float)) or not isfinite(issued):
        return False
    return cutoff is None or issued >= cutoff.replace(tzinfo=timezone.utc).timestamp() * 1000


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


def decode_mcp_access_token(token: str) -> Optional[dict]:
    """Decode an MCP OAuth access token for backend token exchange."""
    try:
        payload = jwt.decode(
            token,
            settings.mcp_jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.mcp_token_audience,
        )
        issuer = str(payload.get("iss") or "").rstrip("/")
        allowed_issuers = settings.allowed_mcp_token_issuers
        if allowed_issuers and issuer not in allowed_issuers:
            return None
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None
