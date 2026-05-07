"""product_reserve_capsules

Revision ID: 20260507_0024
Revises: 20260507_0023
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0024"
down_revision: Union[str, None] = "20260507_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("capsules", sa.Column("capsule_type", sa.String(), nullable=False, server_default="manual"))
    op.add_column("capsules", sa.Column("target_amount_source", sa.String(), nullable=False, server_default="manual"))
    op.add_column("capsules", sa.Column("monthly_contribution_source", sa.String(), nullable=False, server_default="manual"))
    op.add_column("products", sa.Column("funding_capsule_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "products_funding_capsule_id_fkey",
        "products",
        "capsules",
        ["funding_capsule_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("products_funding_capsule_id_fkey", "products", type_="foreignkey")
    op.drop_column("products", "funding_capsule_id")
    op.drop_column("capsules", "monthly_contribution_source")
    op.drop_column("capsules", "target_amount_source")
    op.drop_column("capsules", "capsule_type")
