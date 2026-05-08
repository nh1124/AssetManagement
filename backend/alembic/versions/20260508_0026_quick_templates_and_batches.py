"""add quick templates and transaction batches

Revision ID: 20260508_0026
Revises: 20260507_0025
Create Date: 2026-05-08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260508_0026"
down_revision = "20260507_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quick_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("tray", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("template_kind", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("default_currency", sa.String(), server_default="JPY", nullable=False),
        sa.Column("default_from_account_id", sa.Integer(), nullable=True),
        sa.Column("default_to_account_id", sa.Integer(), nullable=True),
        sa.Column("config", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["default_from_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["default_to_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quick_templates_id"), "quick_templates", ["id"], unique=False)
    op.create_index(op.f("ix_quick_templates_name"), "quick_templates", ["name"], unique=False)
    op.create_index(op.f("ix_quick_templates_tray"), "quick_templates", ["tray"], unique=False)

    op.create_table(
        "transaction_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("quick_template_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("source", sa.String(), server_default="quick", nullable=False),
        sa.Column("input_payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["quick_template_id"], ["quick_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transaction_batches_id"), "transaction_batches", ["id"], unique=False)

    op.add_column("transactions", sa.Column("batch_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_batch_id",
        "transactions",
        "transaction_batches",
        ["batch_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_transactions_batch_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "batch_id")

    op.drop_index(op.f("ix_transaction_batches_id"), table_name="transaction_batches")
    op.drop_table("transaction_batches")

    op.drop_index(op.f("ix_quick_templates_tray"), table_name="quick_templates")
    op.drop_index(op.f("ix_quick_templates_name"), table_name="quick_templates")
    op.drop_index(op.f("ix_quick_templates_id"), table_name="quick_templates")
    op.drop_table("quick_templates")
