"""Require TOTP: staged authentication, lockout and token revocation.

Revision ID: 20261022_0089
Revises: 20261022_0088
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20261022_0089"
down_revision = "20261022_0088"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("locked_until", sa.DateTime(), nullable=True))
    op.add_column("clients", sa.Column("tokens_valid_after", sa.DateTime(), nullable=True))
    op.add_column("clients", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("client_mfa_settings", sa.Column("pending_totp_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("client_mfa_settings", sa.Column("last_totp_step", sa.BigInteger(), nullable=True))
    # Full precision, naive UTC on both PostgreSQL and SQLite.
    op.execute(sa.text("""
        UPDATE clients SET tokens_valid_after = :cutoff
        WHERE NOT EXISTS (
            SELECT 1 FROM client_mfa_settings
            WHERE client_mfa_settings.client_id = clients.id
            AND client_mfa_settings.enabled = true
        )
    """).bindparams(sa.bindparam("cutoff", datetime.utcnow(), type_=sa.DateTime())))


def downgrade():
    op.drop_column("client_mfa_settings", "last_totp_step")
    op.drop_column("client_mfa_settings", "pending_totp_secret_encrypted")
    for column in ("must_change_password", "tokens_valid_after", "locked_until", "failed_login_count"):
        op.drop_column("clients", column)
