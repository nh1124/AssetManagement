"""plan line source identity

Revision ID: 20260528_0034
Revises: 20260524_0033
Create Date: 2026-05-28
"""

import sqlalchemy as sa
from alembic import op


revision = "20260528_0034"
down_revision = "20260524_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("monthly_plan_lines")}
    indexes = {index["name"] for index in inspector.get_indexes("monthly_plan_lines")}

    if "source_kind" not in columns:
        op.add_column(
            "monthly_plan_lines",
            sa.Column("source_kind", sa.String(), server_default="manual", nullable=False),
        )
    if "source_id" not in columns:
        op.add_column("monthly_plan_lines", sa.Column("source_id", sa.Integer(), nullable=True))
    if "identity_key" not in columns:
        op.add_column(
            "monthly_plan_lines",
            sa.Column("identity_key", sa.String(), server_default="", nullable=False),
        )
    if "manual_override" not in columns:
        op.add_column(
            "monthly_plan_lines",
            sa.Column("manual_override", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
    if "ix_monthly_plan_lines_source_identity" not in indexes:
        op.create_index(
            "ix_monthly_plan_lines_source_identity",
            "monthly_plan_lines",
            ["client_id", "plan_id", "target_period", "source_kind", "source_id"],
            unique=False,
        )
    if "uq_monthly_plan_lines_active_identity" not in indexes:
        if bind.dialect.name == "postgresql":
            op.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_monthly_plan_lines_active_identity
                ON monthly_plan_lines (client_id, identity_key)
                WHERE is_active = true AND identity_key <> ''
                """
            )
        else:
            op.create_index(
                "uq_monthly_plan_lines_active_identity",
                "monthly_plan_lines",
                ["client_id", "identity_key"],
                unique=True,
                postgresql_where=sa.text("is_active = true AND identity_key <> ''"),
                sqlite_where=sa.text("is_active = 1 AND identity_key <> ''"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("monthly_plan_lines")}
    indexes = {index["name"] for index in inspector.get_indexes("monthly_plan_lines")}

    if "uq_monthly_plan_lines_active_identity" in indexes:
        op.drop_index("uq_monthly_plan_lines_active_identity", table_name="monthly_plan_lines")
    if "ix_monthly_plan_lines_source_identity" in indexes:
        op.drop_index("ix_monthly_plan_lines_source_identity", table_name="monthly_plan_lines")
    if "manual_override" in columns:
        op.drop_column("monthly_plan_lines", "manual_override")
    if "identity_key" in columns:
        op.drop_column("monthly_plan_lines", "identity_key")
    if "source_id" in columns:
        op.drop_column("monthly_plan_lines", "source_id")
    if "source_kind" in columns:
        op.drop_column("monthly_plan_lines", "source_kind")
