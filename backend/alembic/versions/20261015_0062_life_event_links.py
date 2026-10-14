"""Connect life events into scenario branches without changing their facts."""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0062"
down_revision = "20261014_0061"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "life_event_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("from_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("offset_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "from_event_id", "to_event_id", name="uq_life_event_links_pair"),
        sa.CheckConstraint("kind IN ('after', 'alternative')", name="ck_life_event_links_kind"),
    )


def downgrade():
    op.drop_table("life_event_links")
