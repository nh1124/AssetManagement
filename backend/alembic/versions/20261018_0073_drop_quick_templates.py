"""Drop quick templates: the quick-entry template feature is removed.

Transaction batches stay; only their link to a template goes.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261018_0073"
down_revision = "20261018_0072"
branch_labels = None
depends_on = None


def upgrade():
    # Dropping the column drops its foreign key to quick_templates with it.
    op.execute("ALTER TABLE transaction_batches DROP COLUMN IF EXISTS quick_template_id")
    # Its indexes go with the table.
    op.execute("DROP TABLE IF EXISTS quick_templates")


def downgrade():
    # The templates are gone for good; only the empty table and link come back.
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
    op.add_column("transaction_batches", sa.Column("quick_template_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "transaction_batches_quick_template_id_fkey",
        "transaction_batches",
        "quick_templates",
        ["quick_template_id"],
        ["id"],
    )
