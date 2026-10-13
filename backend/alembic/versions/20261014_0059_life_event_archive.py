"""Keep called-off goals and their savings as reversible history."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_0059"
down_revision = "20261014_0058"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("life_events", sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("life_events", "archived_at")
