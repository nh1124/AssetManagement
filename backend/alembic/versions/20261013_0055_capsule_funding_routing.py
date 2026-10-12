"""Put share declarations on the plan and allow a rule to name its destination."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0055"
down_revision = "20261013_0054"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("max_capsule_share_bp")
    op.add_column("capsule_funding_sources", sa.Column("max_share_bp", sa.Integer(), nullable=True))
    with op.batch_alter_table("capsule_rules") as batch:
        batch.add_column(sa.Column("destination_account_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_capsule_rules_destination_account", "accounts", ["destination_account_id"], ["id"])


def downgrade():
    with op.batch_alter_table("capsule_rules") as batch:
        batch.drop_constraint("fk_capsule_rules_destination_account", type_="foreignkey")
        batch.drop_column("destination_account_id")
    with op.batch_alter_table("capsule_funding_sources") as batch:
        batch.drop_column("max_share_bp")
    op.add_column("accounts", sa.Column("max_capsule_share_bp", sa.Integer(), nullable=True))
