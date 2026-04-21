"""initial schema

Revision ID: 202604200001
Revises:
Create Date: 2026-04-20 00:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202604200001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
