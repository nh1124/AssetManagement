"""ai change requests

Revision ID: 20260606_0039
Revises: 20260606_0038
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op


revision = "20260606_0039"
down_revision = "20260606_0038"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _has_table("ai_change_requests"):
        return

    op.create_table(
        "ai_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("created_by_client_id", sa.Integer(), nullable=True),
        sa.Column("ai_client_id", sa.Integer(), nullable=True),
        sa.Column("mcp_client_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=True),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("risk", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("target_ref", sa.JSON(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("after_snapshot", sa.JSON(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("precondition_hash", sa.String(), nullable=True),
        sa.Column("requires_mfa", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("approved_by_client_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ai_client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["approved_by_client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["created_by_client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "idempotency_key", name="_client_ai_change_request_idempotency_uc"),
    )
    op.create_index(op.f("ix_ai_change_requests_id"), "ai_change_requests", ["id"], unique=False)
    op.create_index(op.f("ix_ai_change_requests_client_id"), "ai_change_requests", ["client_id"], unique=False)
    op.create_index(op.f("ix_ai_change_requests_created_by_client_id"), "ai_change_requests", ["created_by_client_id"], unique=False)
    op.create_index(op.f("ix_ai_change_requests_ai_client_id"), "ai_change_requests", ["ai_client_id"], unique=False)
    op.create_index(op.f("ix_ai_change_requests_mcp_client_id"), "ai_change_requests", ["mcp_client_id"], unique=False)
    op.create_index(op.f("ix_ai_change_requests_status"), "ai_change_requests", ["status"], unique=False)
    op.create_index(op.f("ix_ai_change_requests_approved_by_client_id"), "ai_change_requests", ["approved_by_client_id"], unique=False)


def downgrade() -> None:
    if not _has_table("ai_change_requests"):
        return

    op.drop_index(op.f("ix_ai_change_requests_approved_by_client_id"), table_name="ai_change_requests")
    op.drop_index(op.f("ix_ai_change_requests_status"), table_name="ai_change_requests")
    op.drop_index(op.f("ix_ai_change_requests_mcp_client_id"), table_name="ai_change_requests")
    op.drop_index(op.f("ix_ai_change_requests_ai_client_id"), table_name="ai_change_requests")
    op.drop_index(op.f("ix_ai_change_requests_created_by_client_id"), table_name="ai_change_requests")
    op.drop_index(op.f("ix_ai_change_requests_client_id"), table_name="ai_change_requests")
    op.drop_index(op.f("ix_ai_change_requests_id"), table_name="ai_change_requests")
    op.drop_table("ai_change_requests")
