"""Drop clients.ai_config: the app keeps no AI features and no AI keys."""
from alembic import op
import sqlalchemy as sa

revision = "20261018_0071"
down_revision = "20261017_0070"
branch_labels = None
depends_on = None


def upgrade():
    # The column held only (encrypted) AI API keys; dropping it removes them.
    op.drop_column("clients", "ai_config")


def downgrade():
    # The keys are gone for good; only the empty column comes back.
    op.add_column("clients", sa.Column("ai_config", sa.JSON(), nullable=True))
