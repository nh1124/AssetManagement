"""product_budget_account

Revision ID: 20260507_0023
Revises: 20260507_0022
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0023"
down_revision: Union[str, None] = "20260507_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("budget_account_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "products_budget_account_id_fkey",
        "products",
        "accounts",
        ["budget_account_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("products_budget_account_id_fkey", "products", type_="foreignkey")
    op.drop_column("products", "budget_account_id")
