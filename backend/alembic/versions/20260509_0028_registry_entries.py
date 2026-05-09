"""add registry entries as budget source

Revision ID: 20260509_0028
Revises: 20260509_0027
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260509_0028"
down_revision = "20260509_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registry_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), server_default="0", nullable=False),
        sa.Column("currency", sa.String(), server_default="JPY", nullable=False),
        sa.Column("frequency", sa.String(), server_default="Monthly", nullable=False),
        sa.Column("frequency_days", sa.Integer(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), server_default="1", nullable=False),
        sa.Column("month_of_year", sa.Integer(), nullable=True),
        sa.Column("transaction_type", sa.String(), server_default="Expense", nullable=False),
        sa.Column("line_type", sa.String(), server_default="expense", nullable=False),
        sa.Column("budget_account_id", sa.Integer(), nullable=True),
        sa.Column("source_account_id", sa.Integer(), nullable=True),
        sa.Column("destination_account_id", sa.Integer(), nullable=True),
        sa.Column("funding_capsule_id", sa.Integer(), nullable=True),
        sa.Column("budget_treatment", sa.String(), server_default="expense_only", nullable=False),
        sa.Column("generate_recurring", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("budget_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source_product_id", sa.Integer(), nullable=True),
        sa.Column("source_recurring_transaction_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("start_period", sa.String(), nullable=True),
        sa.Column("end_period", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["budget_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["destination_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["funding_capsule_id"], ["capsules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_recurring_transaction_id"], ["recurring_transactions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_registry_entries_id"), "registry_entries", ["id"], unique=False)
    op.create_index(op.f("ix_registry_entries_name"), "registry_entries", ["name"], unique=False)
    op.add_column("recurring_transactions", sa.Column("source_registry_entry_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "recurring_transactions_source_registry_entry_id_fkey",
        "recurring_transactions",
        "registry_entries",
        ["source_registry_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        INSERT INTO registry_entries (
            client_id, name, entry_type, category, amount, currency, frequency,
            frequency_days, transaction_type, line_type, budget_account_id,
            funding_capsule_id, budget_treatment, generate_recurring, budget_active,
            is_active, source_product_id, created_at, updated_at
        )
        SELECT
            client_id,
            name,
            CASE WHEN is_asset THEN 'asset' ELSE 'item' END,
            category,
            CASE
                WHEN COALESCE(units_per_purchase, 1) > 0 THEN COALESCE(last_unit_price, 0) / COALESCE(units_per_purchase, 1)
                ELSE COALESCE(last_unit_price, 0)
            END,
            'JPY',
            CASE WHEN COALESCE(frequency_days, 0) > 0 THEN 'EveryNDays' ELSE 'Irregular' END,
            NULLIF(frequency_days, 0),
            'Expense',
            CASE
                WHEN is_asset THEN 'allocation'
                WHEN COALESCE(budget_treatment, 'auto') IN ('reserve_allocation', 'asset_replacement') THEN 'allocation'
                WHEN COALESCE(budget_treatment, 'auto') = 'auto' AND (COALESCE(frequency_days, 0) = 0 OR COALESCE(frequency_days, 0) > 45) THEN 'allocation'
                ELSE 'expense'
            END,
            budget_account_id,
            funding_capsule_id,
            COALESCE(budget_treatment, 'auto'),
            false,
            CASE
                WHEN is_asset THEN false
                WHEN COALESCE(budget_treatment, 'auto') IN ('reserve_allocation', 'asset_replacement') THEN false
                WHEN COALESCE(budget_treatment, 'auto') = 'auto' AND (COALESCE(frequency_days, 0) = 0 OR COALESCE(frequency_days, 0) > 45) THEN false
                ELSE true
            END,
            true,
            id,
            now(),
            now()
        FROM products
        WHERE client_id IS NOT NULL
        """
    )

    op.execute(
        """
        INSERT INTO registry_entries (
            client_id, name, entry_type, amount, currency, frequency, day_of_month,
            month_of_year, transaction_type, line_type, budget_account_id,
            source_account_id, destination_account_id, generate_recurring,
            budget_active, is_active, source_recurring_transaction_id,
            start_period, end_period, created_at, updated_at
        )
        SELECT
            client_id,
            name,
            CASE
                WHEN type = 'Income' THEN 'income'
                WHEN type = 'LiabilityPayment' THEN 'debt'
                WHEN type IN ('Transfer', 'CreditAssetPurchase') THEN 'allocation'
                ELSE 'service'
            END,
            COALESCE(amount, 0),
            COALESCE(currency, 'JPY'),
            COALESCE(frequency, 'Monthly'),
            COALESCE(day_of_month, 1),
            month_of_year,
            type,
            CASE
                WHEN type = 'Income' THEN 'income'
                WHEN type = 'Borrowing' THEN 'borrowing'
                WHEN type IN ('Transfer', 'CreditAssetPurchase') THEN 'allocation'
                WHEN type = 'LiabilityPayment' THEN 'debt_payment'
                ELSE 'expense'
            END,
            CASE WHEN type IN ('Expense', 'CreditExpense', 'LiabilityPayment') THEN to_account_id ELSE NULL END,
            from_account_id,
            to_account_id,
            true,
            true,
            COALESCE(is_active, true),
            id,
            start_period,
            end_period,
            now(),
            now()
        FROM recurring_transactions
        WHERE client_id IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE recurring_transactions rt
        SET source_registry_entry_id = re.id
        FROM registry_entries re
        WHERE re.source_recurring_transaction_id = rt.id
        """
    )


def downgrade() -> None:
    op.drop_constraint("recurring_transactions_source_registry_entry_id_fkey", "recurring_transactions", type_="foreignkey")
    op.drop_column("recurring_transactions", "source_registry_entry_id")
    op.drop_index(op.f("ix_registry_entries_name"), table_name="registry_entries")
    op.drop_index(op.f("ix_registry_entries_id"), table_name="registry_entries")
    op.drop_table("registry_entries")
