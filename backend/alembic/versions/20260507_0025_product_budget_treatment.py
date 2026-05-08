"""add product budget treatment

Revision ID: 20260507_0025
Revises: 20260507_0024
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260507_0025"
down_revision = "20260507_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("budget_treatment", sa.String(), nullable=False, server_default="auto"),
    )
    op.alter_column("products", "budget_treatment", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "budget_treatment")
