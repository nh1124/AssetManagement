"""p2 unit economics and monte carlo params

Revision ID: 202604200005
Revises: 202604200004
Create Date: 2026-04-20 00:20:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202604200005"
down_revision: Union[str, None] = "202604200004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS units_per_purchase INTEGER DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE simulation_configs ADD COLUMN IF NOT EXISTS volatility FLOAT DEFAULT 15.0"
    )
    op.execute(
        "ALTER TABLE simulation_configs ADD COLUMN IF NOT EXISTS inflation_rate FLOAT DEFAULT 2.0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE simulation_configs DROP COLUMN IF EXISTS inflation_rate")
    op.execute("ALTER TABLE simulation_configs DROP COLUMN IF EXISTS volatility")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS units_per_purchase")
