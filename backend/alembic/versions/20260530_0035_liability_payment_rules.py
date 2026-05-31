"""liability payment rules

Revision ID: 20260530_0035
Revises: 20260528_0034
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from alembic import op


revision = "20260530_0035"
down_revision = "20260528_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("accounts")}

    if "liability_closing_day" not in columns:
        op.add_column("accounts", sa.Column("liability_closing_day", sa.Integer(), nullable=True))
    if "liability_payment_day" not in columns:
        op.add_column("accounts", sa.Column("liability_payment_day", sa.Integer(), nullable=True))
    if "liability_payment_month_offset" not in columns:
        op.add_column(
            "accounts",
            sa.Column("liability_payment_month_offset", sa.Integer(), server_default="0", nullable=False),
        )
    if "liability_payment_policy" not in columns:
        op.add_column(
            "accounts",
            sa.Column("liability_payment_policy", sa.String(), server_default="full", nullable=False),
        )
    if "liability_minimum_payment" not in columns:
        op.add_column("accounts", sa.Column("liability_minimum_payment", sa.Float(), nullable=True))
    if "liability_fixed_payment_amount" not in columns:
        op.add_column("accounts", sa.Column("liability_fixed_payment_amount", sa.Float(), nullable=True))
    if "liability_installment_months" not in columns:
        op.add_column("accounts", sa.Column("liability_installment_months", sa.Integer(), nullable=True))
    if "liability_revolving_rate" not in columns:
        op.add_column("accounts", sa.Column("liability_revolving_rate", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("accounts")}

    for column in (
        "liability_revolving_rate",
        "liability_installment_months",
        "liability_fixed_payment_amount",
        "liability_minimum_payment",
        "liability_payment_policy",
        "liability_payment_month_offset",
        "liability_payment_day",
        "liability_closing_day",
    ):
        if column in columns:
            op.drop_column("accounts", column)
