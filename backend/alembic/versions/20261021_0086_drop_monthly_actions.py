"""行動 (monthly actions) are gone (owner 2026-10-21): their table and their notifications go.

They only ever wrote money-bearing steps, which automatic transactions and the plan now
cover. Backups before v31 still carry the collection; it is not imported.

Revision ID: 20261021_0086
Revises: 20261021_0085
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0086"
down_revision = "20261021_0085"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM notifications WHERE kind = 'actions_due'")
    op.drop_table("monthly_actions")


def downgrade():
    # The table comes back empty; its rows are in the pre-migration backup.
    op.create_table(
        "monthly_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("source_period", sa.String(), nullable=False),
        sa.Column("target_period", sa.String(), nullable=True),
        sa.Column("proposal_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "idempotency_key", name="_client_action_idempotency_uc"),
    )
    op.create_index("ix_monthly_actions_id", "monthly_actions", ["id"])
