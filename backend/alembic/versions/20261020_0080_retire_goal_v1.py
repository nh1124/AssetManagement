"""Drop what the goal redesign retired (R10).

Tables: milestones, goal_baselines, simulation_scenarios, life_scenario_account_returns
(their yields were copied into scenario_contribution_plans by 0078) and
goal_event_earmarks (their links moved to capsules.goal_event_id in 0079).
Columns: life_events' old plan fields, capsules.life_event_id, the monthly savings of
scenarios and simulation settings, goal_budget_reflections.events and options. No
model maps any of them since 0078/0079; backups at v26/v27 already leave them out.

Downgrade restores the structure only: the dropped rows are not recoverable from
here, only from a database backup taken before the upgrade.

Revision ID: 20261020_0080
Revises: 20261019_0079
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_0080"
down_revision = "20261019_0079"
branch_labels = None
depends_on = None

TABLES = ("goal_event_earmarks", "milestones", "goal_baselines", "simulation_scenarios", "life_scenario_account_returns")


def upgrade():
    bind = op.get_bind()
    counts = {table: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in TABLES}
    for table in TABLES:
        op.drop_table(table)
    with op.batch_alter_table("life_events") as batch:
        batch.drop_constraint("ck_life_events_budget_reflection", type_="check")
        for column in ("start_date", "active_plan_basis", "active_plan_label", "plan_status_override", "budget_reflection", "archived_at"):
            batch.drop_column(column)
    with op.batch_alter_table("capsules") as batch:
        batch.drop_constraint("capsules_life_event_id_fkey", type_="foreignkey")
        batch.drop_column("life_event_id")
    for table in ("life_scenarios", "simulation_configs"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("monthly_savings_minor")
    with op.batch_alter_table("goal_budget_reflections") as batch:
        batch.drop_column("events")
        batch.drop_column("options")
    print("WP20 dropped rows:", counts)


def downgrade():
    with op.batch_alter_table("goal_budget_reflections") as batch:
        batch.add_column(sa.Column("events", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("options", sa.JSON(), nullable=True))
    for table in ("life_scenarios", "simulation_configs"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("monthly_savings_minor", sa.BigInteger(), nullable=True))
    with op.batch_alter_table("capsules") as batch:
        batch.add_column(sa.Column("life_event_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("capsules_life_event_id_fkey", "life_events", ["life_event_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("life_events") as batch:
        batch.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("active_plan_basis", sa.String(), nullable=False, server_default="milestone"))
        batch.add_column(sa.Column("active_plan_label", sa.String(), nullable=True))
        batch.add_column(sa.Column("plan_status_override", sa.String(), nullable=True))
        batch.add_column(sa.Column("budget_reflection", sa.String(), nullable=True))
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch.create_check_constraint("ck_life_events_budget_reflection", "budget_reflection IN ('firm', 'conditional', 'simulation_only')")
    op.create_table(
        "life_scenario_account_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("annual_return", sa.Float(), nullable=False),
        sa.UniqueConstraint("scenario_id", "account_id", name="uq_life_scenario_account_returns_account"),
    )
    op.create_table(
        "simulation_scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("life_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("annual_return", sa.Float(), nullable=False),
        sa.Column("inflation", sa.Float(), nullable=False),
        sa.Column("contribution_schedule", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allocation_mode", sa.String(), nullable=False, server_default="direct"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("monthly_savings_minor", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("client_id", "life_event_id", "name", name="_client_life_event_scenario_name_uc"),
    )
    op.create_index("ix_simulation_scenarios_client_life_event", "simulation_scenarios", ["client_id", "life_event_id"])
    op.create_table(
        "goal_baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False, index=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("life_scenarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scenario_name", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("projection", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("reason IN ('adopted', 'reflection', 'manual')", name="ck_goal_baselines_reason"),
    )
    op.create_index("uq_goal_baselines_current", "goal_baselines", ["client_id"], unique=True, postgresql_where=sa.text("is_current"))
    op.create_table(
        "milestones",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("life_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("source_snapshot", sa.JSON(), nullable=True),
        sa.Column("is_active_plan", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("target_amount_minor", sa.BigInteger(), nullable=True),
    )
    op.create_table(
        "goal_event_earmarks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False, index=True),
        sa.Column("life_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capsule_id", sa.Integer(), sa.ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("share_bp", sa.Integer(), nullable=False, server_default="10000"),
        sa.UniqueConstraint("life_event_id", "capsule_id", name="uq_goal_event_earmarks_pair"),
        sa.CheckConstraint("share_bp >= 0 AND share_bp <= 10000", name="ck_goal_event_earmarks_share"),
    )
