"""Attribute an earmark to its journal leg, without backfilling old movements."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0056"
down_revision = "20261013_0055"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("journal_entries") as batch:
        batch.add_column(sa.Column("capsule_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_journal_entries_capsule", "capsules", ["capsule_id"], ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_journal_entries_capsule_id", ["capsule_id"])


def downgrade():
    with op.batch_alter_table("journal_entries") as batch:
        batch.drop_index("ix_journal_entries_capsule_id")
        batch.drop_constraint("fk_journal_entries_capsule", type_="foreignkey")
        batch.drop_column("capsule_id")
