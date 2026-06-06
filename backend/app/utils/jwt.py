from datetime import datetime, timedelta
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
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expire_minutes)

    expire = datetime.utcnow() + expires_delta

    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": token_type,
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

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
