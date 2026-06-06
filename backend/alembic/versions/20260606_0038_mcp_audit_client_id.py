"""mcp audit client id

Revision ID: 20260606_0038
Revises: 20260606_0037
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op


revision = "20260606_0038"
down_revision = "20260606_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ai_audit_logs")}
    if "mcp_client_id" not in columns:
        op.add_column("ai_audit_logs", sa.Column("mcp_client_id", sa.String(), nullable=True))
        op.create_index(op.f("ix_ai_audit_logs_mcp_client_id"), "ai_audit_logs", ["mcp_client_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ai_audit_logs")}
    if "mcp_client_id" in columns:
        op.drop_index(op.f("ix_ai_audit_logs_mcp_client_id"), table_name="ai_audit_logs")
        op.drop_column("ai_audit_logs", "mcp_client_id")
