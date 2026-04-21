"""p0 liability payment migration

Revision ID: 202604200002
Revises: 202604200001
Create Date: 2026-04-20 00:05:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202604200002"
down_revision: Union[str, None] = "202604200001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE transactions SET type = 'LiabilityPayment' WHERE type = 'Debt'")
    op.execute("UPDATE recurring_transactions SET type = 'LiabilityPayment' WHERE type = 'Debt'")


def downgrade() -> None:
    op.execute("UPDATE transactions SET type = 'Debt' WHERE type = 'LiabilityPayment'")
    op.execute("UPDATE recurring_transactions SET type = 'Debt' WHERE type = 'LiabilityPayment'")
