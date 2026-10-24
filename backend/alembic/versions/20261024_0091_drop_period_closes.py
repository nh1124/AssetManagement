"""月次締め (month close) is gone (owner 2026-10-24): its table and its notifications go.

A close only marked a month as checked; nothing computed from it. Backups before v32
still carry the collection; it is not imported.

Revision ID: 20261024_0091
Revises: 20261022_0090
"""
from alembic import op
import sqlalchemy as sa

revision = "20261024_0091"
down_revision = "20261022_0090"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM notifications WHERE kind = 'month_close'")
    op.drop_table("period_closes")


def downgrade():
    # The table comes back empty; its rows are in the pre-migration backup.
    op.create_table(
        "period_closes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.UniqueConstraint("client_id", "period", name="uq_period_closes_client_period"),
    )
