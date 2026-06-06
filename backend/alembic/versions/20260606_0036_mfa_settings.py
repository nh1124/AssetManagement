"""mfa settings

Revision ID: 20260606_0036
Revises: 20260530_0035
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op


revision = "20260606_0036"
down_revision = "20260530_0035"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("client_mfa_settings"):
        op.create_table(
            "client_mfa_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("enabled_at", sa.DateTime(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("client_id"),
        )
        op.create_index(op.f("ix_client_mfa_settings_id"), "client_mfa_settings", ["id"], unique=False)
        op.create_index(op.f("ix_client_mfa_settings_client_id"), "client_mfa_settings", ["client_id"], unique=False)

    if not _has_table("client_recovery_codes"):
        op.create_table(
            "client_recovery_codes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("code_hash", sa.String(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_client_recovery_codes_id"), "client_recovery_codes", ["id"], unique=False)
        op.create_index(op.f("ix_client_recovery_codes_client_id"), "client_recovery_codes", ["client_id"], unique=False)


def downgrade() -> None:
    if _has_table("client_recovery_codes"):
        op.drop_index(op.f("ix_client_recovery_codes_client_id"), table_name="client_recovery_codes")
        op.drop_index(op.f("ix_client_recovery_codes_id"), table_name="client_recovery_codes")
        op.drop_table("client_recovery_codes")

    if _has_table("client_mfa_settings"):
        op.drop_index(op.f("ix_client_mfa_settings_client_id"), table_name="client_mfa_settings")
        op.drop_index(op.f("ix_client_mfa_settings_id"), table_name="client_mfa_settings")
        op.drop_table("client_mfa_settings")
