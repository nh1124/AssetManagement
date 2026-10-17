"""Store event cash-flow direction, optional subject and scenario horizon."""
from alembic import op
import sqlalchemy as sa

revision = "20261017_0066"
down_revision = "20261015_0065"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("life_events", sa.Column("direction", sa.String(), nullable=False, server_default="expense"))
    op.add_column("life_events", sa.Column("account_id", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_life_events_direction", "life_events", "direction IN ('expense', 'income')")
    op.create_foreign_key("fk_life_events_account_id", "life_events", "accounts", ["account_id"], ["id"], ondelete="SET NULL")
    op.add_column("simulation_configs", sa.Column("horizon_years", sa.Integer(), nullable=False, server_default="30"))
    op.create_check_constraint("ck_simulation_configs_horizon_years", "simulation_configs", "horizon_years BETWEEN 1 AND 60")


def downgrade():
    op.drop_constraint("ck_simulation_configs_horizon_years", "simulation_configs", type_="check")
    op.drop_column("simulation_configs", "horizon_years")
    op.drop_constraint("fk_life_events_account_id", "life_events", type_="foreignkey")
    op.drop_constraint("ck_life_events_direction", "life_events", type_="check")
    op.drop_column("life_events", "account_id")
    op.drop_column("life_events", "direction")
