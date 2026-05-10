"""fix monthly_plan_lines recurring FK to use SET NULL on delete

Revision ID: 20260510_0029
Revises: 20260509_0028
Create Date: 2026-05-10
"""

from alembic import op


revision = "20260510_0029"
down_revision = "20260509_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_monthly_plan_lines_recurring_transaction_id",
        "monthly_plan_lines",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_monthly_plan_lines_recurring_transaction_id",
        "monthly_plan_lines",
        "recurring_transactions",
        ["recurring_transaction_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_monthly_plan_lines_recurring_transaction_id",
        "monthly_plan_lines",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_monthly_plan_lines_recurring_transaction_id",
        "monthly_plan_lines",
        "recurring_transactions",
        ["recurring_transaction_id"],
        ["id"],
    )
