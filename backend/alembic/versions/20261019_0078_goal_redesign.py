"""Goals: contribution plans and goal earmarks, added beside the old data.

Additive only. The yields of life_scenario_account_returns are copied into
scenario_contribution_plans and each event capsule link into goal_event_earmarks.
Retired tables and columns (milestones, goal_baselines, simulation_scenarios,
life_scenario_account_returns, the old life_events plan columns, monthly savings)
stay in the database unmapped until a separate, approved migration drops them.

Revision ID: 20261019_0078
Revises: 20261019_0077
"""
from datetime import date

from alembic import op
import sqlalchemy as sa

revision = "20261019_0078"
down_revision = "20261019_0077"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.create_table(
        "scenario_contribution_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_period", sa.String(7), nullable=False),
        sa.Column("monthly_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("annual_return", sa.Float(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("scenario_id", "account_id", "start_period", name="uq_scenario_contribution_plans_month"),
        sa.CheckConstraint("monthly_amount_minor >= 0", name="ck_scenario_contribution_plans_amount"),
    )
    # Each scenario's account yields become records from this month with no amount.
    moved_returns = bind.execute(sa.text(
        "INSERT INTO scenario_contribution_plans (scenario_id, account_id, start_period, monthly_amount_minor, annual_return, created_at) "
        "SELECT scenario_id, account_id, :period, 0, annual_return, CURRENT_TIMESTAMP FROM life_scenario_account_returns"
    ), {"period": date.today().strftime("%Y-%m")}).rowcount

    op.create_table(
        "goal_event_earmarks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False, index=True),
        sa.Column("life_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capsule_id", sa.Integer(), sa.ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("share_bp", sa.Integer(), nullable=False, server_default="10000"),
        sa.UniqueConstraint("life_event_id", "capsule_id", name="uq_goal_event_earmarks_pair"),
        sa.CheckConstraint("share_bp BETWEEN 0 AND 10000", name="ck_goal_event_earmarks_share"),
    )
    moved_links = bind.execute(sa.text(
        "INSERT INTO goal_event_earmarks (client_id, life_event_id, capsule_id, share_bp) "
        "SELECT client_id, life_event_id, id, 10000 FROM capsules WHERE life_event_id IS NOT NULL AND client_id IS NOT NULL"
    )).rowcount
    # The old link deletes its capsule with the event (ON DELETE CASCADE); now that the
    # link lives in goal_event_earmarks, clear it so a real earmark is never cascaded away.
    bind.execute(sa.text("UPDATE capsules SET life_event_id = NULL WHERE life_event_id IS NOT NULL"))

    # New reflection records keep only their summary.
    with op.batch_alter_table("goal_budget_reflections") as batch:
        batch.alter_column("options", existing_type=sa.JSON(), nullable=True)
        batch.alter_column("events", existing_type=sa.JSON(), nullable=True)
    print(f"WP15 migration counts: {{'account_returns_copied': {moved_returns}, 'event_earmarks_copied': {moved_links}}}")


def downgrade():
    with op.batch_alter_table("goal_budget_reflections") as batch:
        batch.alter_column("events", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("options", existing_type=sa.JSON(), nullable=False)
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE capsules SET life_event_id = (SELECT g.life_event_id FROM goal_event_earmarks g "
        "WHERE g.capsule_id = capsules.id ORDER BY g.id LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM goal_event_earmarks g WHERE g.capsule_id = capsules.id)"
    ))
    op.drop_table("goal_event_earmarks")
    op.drop_table("scenario_contribution_plans")
