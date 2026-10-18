"""The registry owns the automatic-recording settings.

auto_post moves from the generated recurring row to its registry entry, which
now writes it one way like every other field. auto_depreciation is new: a
product-backed entry that writes its asset down on its own.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261019_0074"
down_revision = "20261018_0073"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "registry_entries",
        sa.Column("auto_post", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "registry_entries",
        sa.Column("auto_depreciation", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # The user's manual-approval choice was kept on the recurring row.
    op.execute(
        """
        UPDATE registry_entries AS entry
        SET auto_post = recurring.auto_post
        FROM recurring_transactions AS recurring
        WHERE recurring.source_registry_entry_id = entry.id
        """
    )


def downgrade():
    op.drop_column("registry_entries", "auto_depreciation")
    op.drop_column("registry_entries", "auto_post")
