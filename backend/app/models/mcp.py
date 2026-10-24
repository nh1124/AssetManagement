"""MCP OAuth state (WP35): the apps registered through DCR and the connections people made.

A connection is one person's grant to one AI app. It holds the authorization code
until the app redeems it, then the hash of the app's refresh token. The MCP server
keeps none of this and asks the backend instead (owner 2026-10-24, C2), so
re-creating the MCP container no longer signs everyone out.
"""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, JSON, String

from ..database import Base


class McpOAuthClient(Base):
    """An app registered through Dynamic Client Registration (RFC 7591).

    Apps that publish a client ID metadata document (Claude Code) have no row:
    the MCP server reads their document instead.
    """
    __tablename__ = "mcp_oauth_clients"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String, unique=True, nullable=False, index=True)
    client_name = Column(String, nullable=True)
    redirect_uris = Column(JSON, nullable=False, default=list)
    grant_types = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)


class McpConnection(Base):
    """One person's grant to one AI app: pending until its code is redeemed, then active."""
    __tablename__ = "mcp_connections"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    # The app: a metadata document URL (cimd) or a registered mcp_… id (dcr).
    oauth_client_id = Column(String, nullable=False, index=True)
    client_name = Column(String, nullable=True)
    client_source = Column(String, nullable=False)
    redirect_uri = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    resource = Column(String, nullable=False)
    issuer = Column(String, nullable=False)
    # When the person signed in to grant it; every token of the connection carries it,
    # so a password change (tokens_valid_after) ends the connection too.
    auth_time_ms = Column(BigInteger, nullable=False)
    allow_refresh = Column(Boolean, nullable=False, default=False)
    code_hash = Column(String, unique=True, nullable=True)
    code_challenge = Column(String, nullable=True)
    refresh_token_hash = Column(String, unique=True, nullable=True)
    previous_refresh_token_hash = Column(String, unique=True, nullable=True)
    refreshed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    activated_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    # The code's expiry while pending; then the refresh token's (30 days, renewed on
    # use), or the access token's for an app that takes no refresh token.
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String, nullable=True)
