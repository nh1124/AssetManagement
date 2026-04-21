"""p1 budget to monthly budget migration

Revision ID: 202604200004
Revises: 202604200003
Create Date: 2026-04-20 00:15:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202604200004"
down_revision: Union[str, None] = "202604200003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO monthly_budgets (id, client_id, account_id, target_period, amount)
        SELECT
            md5(random()::text || clock_timestamp()::text)::uuid,
            b.client_id,
            a.id,
            b.month,
            b.proposed_amount
        FROM budgets b
        JOIN accounts a ON a.name = b.category AND a.client_id = b.client_id
        ON CONFLICT (account_id, target_period) DO NOTHING
        """
    )
    op.execute("DROP TABLE IF EXISTS budgets")


def downgrade() -> None:
    # Legacy budgets table is intentionally not restored.
    pass
