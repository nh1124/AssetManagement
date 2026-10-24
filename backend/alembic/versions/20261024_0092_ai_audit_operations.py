"""Every MCP request becomes an AI audit row (owner 2026-10-24, WP34).

The row says what let the operation through or stopped it (authorization), the
HTTP status it ended with, and the backend request and MCP tool call it belongs
to. Existing rows keep NULL in all four: they were written by the change-request
workflow and the context reads, before the request was recorded.

Revision ID: 20261024_0092
Revises: 20261024_0091
"""
from alembic import op
import sqlalchemy as sa

revision = "20261024_0092"
down_revision = "20261024_0091"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_audit_logs", sa.Column("authorization", sa.String(), nullable=True))
    op.add_column("ai_audit_logs", sa.Column("http_status", sa.Integer(), nullable=True))
    op.add_column("ai_audit_logs", sa.Column("request_id", sa.String(), nullable=True))
    op.add_column("ai_audit_logs", sa.Column("correlation_id", sa.String(), nullable=True))
    op.create_index("ix_ai_audit_logs_request_id", "ai_audit_logs", ["request_id"])
    op.create_index("ix_ai_audit_logs_correlation_id", "ai_audit_logs", ["correlation_id"])


def downgrade():
    op.drop_index("ix_ai_audit_logs_correlation_id", table_name="ai_audit_logs")
    op.drop_index("ix_ai_audit_logs_request_id", table_name="ai_audit_logs")
    op.drop_column("ai_audit_logs", "correlation_id")
    op.drop_column("ai_audit_logs", "request_id")
    op.drop_column("ai_audit_logs", "http_status")
    op.drop_column("ai_audit_logs", "authorization")
