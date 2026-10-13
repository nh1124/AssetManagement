"""Mark reviewed months without locking their journal entries."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_0060"
down_revision = "20261014_0059"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "period_closes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.UniqueConstraint("client_id", "period", name="uq_period_closes_client_period"),
    )


def downgrade():
    op.drop_table("period_closes")
