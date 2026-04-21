"""p3 capsule account sync and drop settings

Revision ID: 202604200006
Revises: 202604200005
Create Date: 2026-04-20 00:25:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202604200006"
down_revision: Union[str, None] = "202604200005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE capsules ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES accounts(id)"
    )
    op.execute("DROP TABLE IF EXISTS settings")


def downgrade() -> None:
    op.execute("ALTER TABLE capsules DROP COLUMN IF EXISTS account_id")
