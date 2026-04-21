"""p1 transaction account fk

Revision ID: 202604200003
Revises: 202604200002
Create Date: 2026-04-20 00:10:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202604200003"
down_revision: Union[str, None] = "202604200002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE transactions "
        "ADD COLUMN IF NOT EXISTS from_account_id INTEGER REFERENCES accounts(id)"
    )
    op.execute(
        "ALTER TABLE transactions "
        "ADD COLUMN IF NOT EXISTS to_account_id INTEGER REFERENCES accounts(id)"
    )
    op.execute(
        """
        UPDATE transactions t
        SET from_account_id = a.id
        FROM accounts a
        WHERE a.name = t.from_account
          AND a.client_id = t.client_id
          AND t.from_account_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE transactions t
        SET to_account_id = a.id
        FROM accounts a
        WHERE a.name = t.to_account
          AND a.client_id = t.client_id
          AND t.to_account_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS from_account_id")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS to_account_id")
