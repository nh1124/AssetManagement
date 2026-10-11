"""Add capsule reservation approval setting.

Revision ID: 20261011_0050
Revises: 20261011_0049
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261011_0050"
down_revision: Union[str, None] = "20261011_0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("capsules", sa.Column("auto_post", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("capsules", "auto_post")
