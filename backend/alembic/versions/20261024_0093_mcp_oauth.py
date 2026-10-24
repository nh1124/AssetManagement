"""MCP OAuth state moves from the MCP server's memory to the database (owner 2026-10-24, WP35).

mcp_oauth_clients holds the apps registered through DCR; mcp_connections holds
each person's grant to an app (the pending code, then the refresh token's hash).
Both start empty: the registrations and refresh tokens in the old MCP process
are not carried over, so everyone connects once more after this deploy.

Revision ID: 20261024_0093
Revises: 20261024_0092
"""
from alembic import op
import sqlalchemy as sa

revision = "20261024_0093"
down_revision = "20261024_0092"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("mcp_oauth_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=True),
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column("grant_types", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_mcp_oauth_clients_id", "mcp_oauth_clients", ["id"])
    op.create_index("ix_mcp_oauth_clients_client_id", "mcp_oauth_clients", ["client_id"], unique=True)
    op.create_table("mcp_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("oauth_client_id", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=True),
        sa.Column("client_source", sa.String(), nullable=False),
        sa.Column("redirect_uri", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("auth_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("allow_refresh", sa.Boolean(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=True, unique=True),
        sa.Column("code_challenge", sa.String(), nullable=True),
        sa.Column("refresh_token_hash", sa.String(), nullable=True, unique=True),
        sa.Column("previous_refresh_token_hash", sa.String(), nullable=True, unique=True),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.String(), nullable=True),
    )
    op.create_index("ix_mcp_connections_id", "mcp_connections", ["id"])
    op.create_index("ix_mcp_connections_client_id", "mcp_connections", ["client_id"])
    op.create_index("ix_mcp_connections_oauth_client_id", "mcp_connections", ["oauth_client_id"])


def downgrade():
    op.drop_index("ix_mcp_connections_oauth_client_id", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_client_id", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_id", table_name="mcp_connections")
    op.drop_table("mcp_connections")
    op.drop_index("ix_mcp_oauth_clients_client_id", table_name="mcp_oauth_clients")
    op.drop_index("ix_mcp_oauth_clients_id", table_name="mcp_oauth_clients")
    op.drop_table("mcp_oauth_clients")
