"""ai operation policy audit

Revision ID: 20260606_0037
Revises: 20260606_0036
Create Date: 2026-06-06
"""

import sqlalchemy as sa
from alembic import op


revision = "20260606_0037"
down_revision = "20260606_0036"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _has_table("ai_operation_policies"):
        op.create_table(
            "ai_operation_policies",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("ai_client_id", sa.Integer(), nullable=True),
            sa.Column("resource", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("risk", sa.String(), nullable=False),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("threshold_amount", sa.Float(), nullable=True),
            sa.Column("threshold_count", sa.Integer(), nullable=True),
            sa.Column("require_mfa", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["ai_client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "client_id",
                "ai_client_id",
                "resource",
                "action",
                "risk",
                name="_client_ai_policy_uc",
            ),
        )
        op.create_index(op.f("ix_ai_operation_policies_id"), "ai_operation_policies", ["id"], unique=False)
        op.create_index(op.f("ix_ai_operation_policies_client_id"), "ai_operation_policies", ["client_id"], unique=False)
        op.create_index(op.f("ix_ai_operation_policies_ai_client_id"), "ai_operation_policies", ["ai_client_id"], unique=False)

    if not _has_table("ai_audit_logs"):
        op.create_table(
            "ai_audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("actor_client_id", sa.Integer(), nullable=True),
            sa.Column("ai_client_id", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("tool_name", sa.String(), nullable=True),
            sa.Column("resource", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("risk", sa.String(), nullable=False),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("request_summary", sa.JSON(), nullable=False),
            sa.Column("diff_summary", sa.JSON(), nullable=False),
            sa.Column("result_summary", sa.JSON(), nullable=False),
            sa.Column("approval_request_id", sa.Integer(), nullable=True),
            sa.Column("mfa_verified", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("user_agent", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["actor_client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["ai_client_id"], ["clients.id"]),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_ai_audit_logs_id"), "ai_audit_logs", ["id"], unique=False)
        op.create_index(op.f("ix_ai_audit_logs_client_id"), "ai_audit_logs", ["client_id"], unique=False)
        op.create_index(op.f("ix_ai_audit_logs_actor_client_id"), "ai_audit_logs", ["actor_client_id"], unique=False)
        op.create_index(op.f("ix_ai_audit_logs_ai_client_id"), "ai_audit_logs", ["ai_client_id"], unique=False)


def downgrade() -> None:
    if _has_table("ai_audit_logs"):
        op.drop_index(op.f("ix_ai_audit_logs_ai_client_id"), table_name="ai_audit_logs")
        op.drop_index(op.f("ix_ai_audit_logs_actor_client_id"), table_name="ai_audit_logs")
        op.drop_index(op.f("ix_ai_audit_logs_client_id"), table_name="ai_audit_logs")
        op.drop_index(op.f("ix_ai_audit_logs_id"), table_name="ai_audit_logs")
        op.drop_table("ai_audit_logs")

    if _has_table("ai_operation_policies"):
        op.drop_index(op.f("ix_ai_operation_policies_ai_client_id"), table_name="ai_operation_policies")
        op.drop_index(op.f("ix_ai_operation_policies_client_id"), table_name="ai_operation_policies")
        op.drop_index(op.f("ix_ai_operation_policies_id"), table_name="ai_operation_policies")
        op.drop_table("ai_operation_policies")
