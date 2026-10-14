"""Write assets down in the journal instead of only in a report."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_0061"
down_revision = "20261014_0060"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column(
        "depreciation_method", sa.String(), nullable=False, server_default="none",
    ))
    op.add_column("products", sa.Column("depreciation_annual_rate", sa.Float(), nullable=True))
    op.add_column("products", sa.Column(
        "depreciation_interval", sa.String(), nullable=False, server_default="monthly",
    ))
    op.add_column("products", sa.Column("depreciation_start_date", sa.Date(), nullable=True))
    op.add_column("products", sa.Column("depreciation_expense_account_id", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("depreciation_asset_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_products_depreciation_expense_account", "products", "accounts",
        ["depreciation_expense_account_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_products_depreciation_asset_account", "products", "accounts",
        ["depreciation_asset_account_id"], ["id"], ondelete="SET NULL",
    )
    # Existing rows keep 'none': nothing is written down until someone says how.
    op.create_check_constraint(
        "ck_product_depreciation_method", "products",
        "depreciation_method IN ('none', 'straight_line', 'declining_balance')",
    )
    op.create_check_constraint(
        "ck_product_depreciation_interval", "products",
        "depreciation_interval IN ('monthly', 'yearly')",
    )

    op.create_table(
        "product_depreciations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "product_id", "period", name="uq_product_depreciation_period"),
    )
    op.create_index("ix_product_depreciations_product_id", "product_depreciations", ["product_id"])


def downgrade():
    op.drop_index("ix_product_depreciations_product_id", table_name="product_depreciations")
    op.drop_table("product_depreciations")
    op.drop_constraint("ck_product_depreciation_interval", "products", type_="check")
    op.drop_constraint("ck_product_depreciation_method", "products", type_="check")
    op.drop_constraint("fk_products_depreciation_asset_account", "products", type_="foreignkey")
    op.drop_constraint("fk_products_depreciation_expense_account", "products", type_="foreignkey")
    for column in (
        "depreciation_asset_account_id",
        "depreciation_expense_account_id",
        "depreciation_start_date",
        "depreciation_interval",
        "depreciation_annual_rate",
        "depreciation_method",
    ):
        op.drop_column("products", column)
