"""Separate administrator identities, audit, sessions and installation settings.

Revision ID: 20261022_0090
Revises: 20261022_0089
"""
from alembic import op
import sqlalchemy as sa

revision = "20261022_0090"
down_revision = "20261022_0089"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("approval_pending", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("clients", sa.Column("suspended_reason", sa.Text(), nullable=True))
    op.create_table("admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_totp_step", sa.BigInteger(), nullable=True),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("tokens_valid_after", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("username = lower(username)", name="ck_admin_username_lower"),
    )
    op.create_table("admin_user_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=False),
        sa.Column("permission", sa.String(), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("granted_by", sa.String(), nullable=False),
        sa.UniqueConstraint("admin_user_id", "permission", name="uq_admin_permission"),
    )
    op.create_index("ix_admin_user_permissions_admin_user_id", "admin_user_permissions", ["admin_user_id"])
    op.create_table("admin_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("stepped_up_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index("ix_admin_sessions_admin_user_id", "admin_sessions", ["admin_user_id"])
    op.create_table("admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_client_id", sa.Integer(), nullable=True),
        sa.Column("target_admin_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.CheckConstraint("result IN ('ok', 'refused', 'failed')", name="ck_admin_audit_result"),
    )
    op.create_index("ix_admin_audit_logs_at", "admin_audit_logs", ["at"])
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
    op.create_table("system_settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
    )


def downgrade():
    for table in ("system_settings", "admin_audit_logs", "admin_sessions", "admin_user_permissions", "admin_users"):
        op.drop_table(table)
    op.drop_column("clients", "suspended_reason")
    op.drop_column("clients", "approval_pending")
