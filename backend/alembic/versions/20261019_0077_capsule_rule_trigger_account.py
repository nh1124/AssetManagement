"""Allow an earmark rule to require a journal account or subject."""
from alembic import op
import sqlalchemy as sa

revision = "20261019_0077"
down_revision = "20261019_0076"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("capsule_rules") as batch:
        batch.add_column(sa.Column("trigger_account_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_capsule_rules_trigger_account", "accounts", ["trigger_account_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("capsule_rules") as batch:
        batch.drop_constraint("fk_capsule_rules_trigger_account", type_="foreignkey")
        batch.drop_column("trigger_account_id")
