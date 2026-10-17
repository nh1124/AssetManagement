"""Keep goal baselines and the record of each goal-to-budget reflection."""
from alembic import op
import sqlalchemy as sa

revision = "20261017_0070"
down_revision = "20261017_0069"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "goal_baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scenario_name", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("projection", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime()),
        sa.CheckConstraint("reason IN ('adopted', 'reflection', 'manual')", name="ck_goal_baselines_reason"),
    )
    op.create_index("ix_goal_baselines_client_id", "goal_baselines", ["client_id"])
    op.create_index("uq_goal_baselines_current", "goal_baselines", ["client_id"], unique=True,
                    postgresql_where=sa.text("is_current"), sqlite_where=sa.text("is_current"))
    op.create_table(
        "goal_budget_reflections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("start_period", sa.String(7), nullable=False),
        sa.Column("end_period", sa.String(7), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
    )
    op.create_index("ix_goal_budget_reflections_client_id", "goal_budget_reflections", ["client_id"])


def downgrade():
    op.drop_index("ix_goal_budget_reflections_client_id", table_name="goal_budget_reflections")
    op.drop_table("goal_budget_reflections")
    op.drop_index("uq_goal_baselines_current", table_name="goal_baselines")
    op.drop_index("ix_goal_baselines_client_id", table_name="goal_baselines")
    op.drop_table("goal_baselines")
