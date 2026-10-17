"""Give each scenario its monthly savings and each life event a budget reflection."""
from alembic import op
import sqlalchemy as sa

revision = "20261017_0069"
down_revision = "20261017_0068"
branch_labels = None
depends_on = None


def upgrade():
    # NULL keeps today's behaviour: the client-wide simulation setting applies.
    op.add_column("life_scenarios", sa.Column("monthly_savings_minor", sa.BigInteger(), nullable=True))
    op.add_column("life_events", sa.Column("budget_reflection", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_life_events_budget_reflection", "life_events",
        "budget_reflection IN ('firm', 'conditional', 'simulation_only')",
    )


def downgrade():
    op.drop_constraint("ck_life_events_budget_reflection", "life_events", type_="check")
    op.drop_column("life_events", "budget_reflection")
    op.drop_column("life_scenarios", "monthly_savings_minor")
