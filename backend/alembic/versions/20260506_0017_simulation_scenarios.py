"""simulation_scenarios

Revision ID: 20260506_0017
Revises: 20260506_0016
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260506_0017"
down_revision: Union[str, None] = "20260506_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "simulation_scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("life_event_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("annual_return", sa.Float(), nullable=False),
        sa.Column("inflation", sa.Float(), nullable=False),
        sa.Column("monthly_savings", sa.Float(), nullable=True),
        sa.Column("contribution_schedule", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allocation_mode", sa.String(), nullable=False, server_default="direct"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["life_event_id"], ["life_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id", "life_event_id", "name", name="_client_life_event_scenario_name_uc"),
    )
    op.create_index(
        "ix_simulation_scenarios_client_life_event",
        "simulation_scenarios",
        ["client_id", "life_event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_simulation_scenarios_client_life_event", table_name="simulation_scenarios")
    op.drop_table("simulation_scenarios")
