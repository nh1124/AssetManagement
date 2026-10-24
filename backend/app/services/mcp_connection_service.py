"""The MCP OAuth state: DCR registrations and each person's connections (WP35).

The MCP server is the OAuth front door (consent page, client metadata documents,
redirect URI checks); this module decides what a code or a refresh token is worth
and keeps the record, so a connection survives the MCP container and can be ended
on its own (owner 2026-10-24, C1-C3, C5).

Codes and refresh tokens are stored as SHA-256 hashes only.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid, NotFound, Refused

AUTH_CODE_TTL = timedelta(minutes=5)
ACCESS_TOKEN_TTL = timedelta(hours=1)
# Renewed on every use: 30 days without one ends the connection (RFC 9700 §4.14.2).
REFRESH_TOKEN_TTL = timedelta(days=30)
# A client that refreshes twice at once presents the token it just replaced; inside
# this window that is a race, after it a replay that ends the connection.
REFRESH_REUSE_GRACE = timedelta(seconds=60)
# DCR registrations nothing used for this long are removed (RFC 7591 §5).
UNUSED_REGISTRATION_TTL = timedelta(days=30)
MAX_REGISTERED_CLIENTS = 1000
# Revoked and expired connections stay listed in the database this long, then go.
ENDED_CONNECTION_RETENTION = timedelta(days=30)

GRANT_TYPES = ("authorization_code", "refresh_token")
SOURCES = ("cimd", "dcr")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class InvalidGrant(Invalid):
    """The code or refresh token is unknown, used up, expired, revoked or someone else's."""

    def __init__(self, reason: str):
        super().__init__(f"invalid_grant: {reason}", payload={"error": "invalid_grant"})
        self.reason = reason


def _hash(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode("utf-8")).digest()).rstrip(b"=").decode("ascii")


def _now(now: datetime | None) -> datetime:
    return now or datetime.utcnow()


# ─── DCR registrations ─────────────────────────────────────

def _valid_redirect_uri(uri: str) -> bool:
    """https, or http on a loopback host (MCP authorization: localhost or HTTPS only)."""
    try:
        parts = urlsplit(uri)
        hostname = parts.hostname
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not hostname:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and hostname in LOOPBACK_HOSTS)


def register_client(
    db: Session, *, client_name: str | None, redirect_uris: list[str], grant_types: list[str],
    now: datetime | None = None,
) -> models.McpOAuthClient:
    now = _now(now)
    uris = [uri.strip() for uri in redirect_uris if isinstance(uri, str) and uri.strip()]
    if not uris or not all(_valid_redirect_uri(uri) for uri in uris):
        raise Invalid("redirect_uris must be https or loopback http URLs",
                      payload={"error": "invalid_redirect_uri"})
    grants = [grant for grant in GRANT_TYPES if grant in grant_types or grant == "authorization_code"]
    _remove_unused_registrations(db, now)
    if db.query(models.McpOAuthClient).count() >= MAX_REGISTERED_CLIENTS:
        raise Refused("Too many registered MCP clients", status_code=429,
                      payload={"error": "temporarily_unavailable"})
    row = models.McpOAuthClient(
        client_id=f"mcp_{secrets.token_hex(16)}",
        client_name=(client_name or "").strip()[:200] or None,
        redirect_uris=uris,
        grant_types=grants,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_registered_client(db: Session, client_id: str) -> models.McpOAuthClient | None:
    return db.query(models.McpOAuthClient).filter(models.McpOAuthClient.client_id == client_id).first()


def _remove_unused_registrations(db: Session, now: datetime) -> None:
    cutoff = now - UNUSED_REGISTRATION_TTL
    db.query(models.McpOAuthClient).filter(
        models.McpOAuthClient.created_at < cutoff,
        or_(models.McpOAuthClient.last_used_at.is_(None), models.McpOAuthClient.last_used_at < cutoff),
    ).delete(synchronize_session=False)


def _mark_registration_used(db: Session, oauth_client_id: str, now: datetime) -> None:
    db.query(models.McpOAuthClient).filter(
        models.McpOAuthClient.client_id == oauth_client_id,
    ).update({models.McpOAuthClient.last_used_at: now}, synchronize_session=False)


# ─── Connections ───────────────────────────────────────────

def _remove_ended_connections(db: Session, now: datetime) -> None:
    pending = (models.McpConnection.activated_at.is_(None)) & (models.McpConnection.expires_at < now)
    cutoff = now - ENDED_CONNECTION_RETENTION
    ended = (models.McpConnection.revoked_at < cutoff) | (models.McpConnection.expires_at < cutoff)
    db.query(models.McpConnection).filter(pending | ended).delete(synchronize_session=False)


def start_connection(
    db: Session, *, client_id: int, oauth_client_id: str, client_name: str | None, client_source: str,
    redirect_uri: str, code_challenge: str, scope: str, resource: str, issuer: str,
    allow_refresh: bool, auth_time_ms: int, now: datetime | None = None,
) -> str:
    """Record a pending connection for a person who just signed in; returns its authorization code."""
    now = _now(now)
    if client_source not in SOURCES:
        raise Invalid(f"Unknown client source: {client_source}", payload={"error": "invalid_request"})
    _remove_ended_connections(db, now)
    code = secrets.token_urlsafe(32)
    db.add(models.McpConnection(
        client_id=client_id,
        oauth_client_id=oauth_client_id,
        client_name=(client_name or "").strip()[:200] or None,
        client_source=client_source,
        redirect_uri=redirect_uri,
        scope=scope or "mcp",
        resource=resource,
        issuer=issuer,
        auth_time_ms=int(auth_time_ms),
        allow_refresh=allow_refresh,
        code_hash=_hash(code),
        code_challenge=code_challenge,
        created_at=now,
        expires_at=now + AUTH_CODE_TTL,
    ))
    db.commit()
    return code


def _new_refresh_token(connection: models.McpConnection, now: datetime) -> str:
    token = secrets.token_urlsafe(48)
    connection.refresh_token_hash = _hash(token)
    connection.refreshed_at = now
    connection.expires_at = now + REFRESH_TOKEN_TTL
    return token


def _pkce_matches(verifier: str, challenge: str | None) -> bool:
    # S256 only: with "plain" anyone who saw the authorize request could redeem the code.
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii", "replace")).digest()).rstrip(b"=")
    return bool(challenge) and secrets.compare_digest(digest.decode("ascii"), challenge)


def redeem_code(
    db: Session, *, code: str, oauth_client_id: str, redirect_uri: str, code_verifier: str,
    now: datetime | None = None,
) -> tuple[models.McpConnection, str | None]:
    """Activate the connection behind a code; returns it and its first refresh token, if any.

    A code is single use: any mismatch spends it, as an attacker may be guessing.
    """
    now = _now(now)
    connection = db.query(models.McpConnection).filter(models.McpConnection.code_hash == _hash(code)).first()
    if connection is None:
        raise InvalidGrant("code not found")
    failure = (
        "code expired" if connection.expires_at <= now
        else "client mismatch" if connection.oauth_client_id != oauth_client_id
        # RFC 6749 §4.1.3: the same redirect URI as the authorize request, port included.
        else "redirect_uri mismatch" if connection.redirect_uri != redirect_uri
        else "PKCE verification failed" if not _pkce_matches(code_verifier, connection.code_challenge)
        else None
    )
    if failure:
        db.delete(connection)
        db.commit()
        raise InvalidGrant(failure)
    connection.code_hash = None
    connection.code_challenge = None
    connection.activated_at = now
    connection.last_used_at = now
    refresh_token = _new_refresh_token(connection, now) if connection.allow_refresh else None
    if refresh_token is None:
        connection.expires_at = now + ACCESS_TOKEN_TTL
    _mark_registration_used(db, oauth_client_id, now)
    db.commit()
    db.refresh(connection)
    return connection, refresh_token


def refresh(
    db: Session, *, refresh_token: str, oauth_client_id: str, now: datetime | None = None,
) -> tuple[models.McpConnection, str]:
    """Rotate a refresh token (OAuth 2.1 §4.3.1); a replayed one ends the connection."""
    now = _now(now)
    token_hash = _hash(refresh_token)
    connection = db.query(models.McpConnection).filter(models.McpConnection.refresh_token_hash == token_hash).first()
    replaced = None
    if connection is None:
        replaced = db.query(models.McpConnection).filter(
            models.McpConnection.previous_refresh_token_hash == token_hash).first()
        if replaced is None:
            raise InvalidGrant("refresh token not found")
        if replaced.revoked_at is None and not (replaced.refreshed_at and now - replaced.refreshed_at <= REFRESH_REUSE_GRACE):
            # The legitimate client and an attacker cannot be told apart: end it (RFC 9700 §4.14.2).
            replaced.revoked_at = now
            replaced.revoked_reason = "refresh_reuse"
            db.commit()
            raise InvalidGrant("refresh token reused")
        connection = replaced
    failure = (
        "client mismatch" if connection.oauth_client_id != oauth_client_id
        else "connection revoked" if connection.revoked_at is not None
        else "refresh not allowed" if not connection.allow_refresh or connection.activated_at is None
        else "refresh token expired" if connection.expires_at <= now
        else None
    )
    if failure:
        raise InvalidGrant(failure)
    if replaced is None:
        connection.previous_refresh_token_hash = connection.refresh_token_hash
    new_token = _new_refresh_token(connection, now)
    connection.last_used_at = now
    _mark_registration_used(db, oauth_client_id, now)
    db.commit()
    db.refresh(connection)
    return connection, new_token


def _live(query, now: datetime):
    return query.filter(
        models.McpConnection.activated_at.isnot(None),
        models.McpConnection.revoked_at.is_(None),
        models.McpConnection.expires_at > now,
    )


def active_connection(
    db: Session, connection_id: int, client_id: int, *, now: datetime | None = None,
) -> models.McpConnection | None:
    """The connection if it still stands for this person: activated, not revoked, not expired."""
    return _live(db.query(models.McpConnection).filter(
        models.McpConnection.id == connection_id,
        models.McpConnection.client_id == client_id,
    ), _now(now)).first()


def record_use(db: Session, connection: models.McpConnection, *, now: datetime | None = None) -> None:
    connection.last_used_at = _now(now)
    db.commit()


def list_connections(db: Session, client_id: int, *, now: datetime | None = None) -> list[models.McpConnection]:
    """The person's standing connections, newest first."""
    return _live(db.query(models.McpConnection).filter(models.McpConnection.client_id == client_id), _now(now)) \
        .order_by(models.McpConnection.activated_at.desc(), models.McpConnection.id.desc()).all()


def revoke(
    db: Session, client_id: int, connection_id: int, *, reason: str = "user", now: datetime | None = None,
) -> models.McpConnection:
    """End one connection: its refresh token stops working and its access tokens are refused."""
    connection = active_connection(db, connection_id, client_id, now=now)
    if connection is None:
        raise NotFound("MCP connection not found", ja="接続が見つかりません。")
    connection.revoked_at = _now(now)
    connection.revoked_reason = reason
    db.commit()
    return connection
