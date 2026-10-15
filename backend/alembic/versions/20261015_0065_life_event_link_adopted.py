"""Keep adoption on the edge so removing a choice also removes its adoption."""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0065"
down_revision = "20261015_0064"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("life_event_links", sa.Column("adopted", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("life_event_links", "adopted")
