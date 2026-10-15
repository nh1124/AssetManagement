"""Record assumptions and household facts without changing the simulation."""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0063"
down_revision = "20261015_0062"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("life_events", sa.Column("condition_mode", sa.String(), nullable=False, server_default="all"))
    op.create_check_constraint("ck_life_events_condition_mode", "life_events", "condition_mode IN ('all', 'any')")
    op.create_table(
        "household_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "name", name="uq_household_members_name"),
    )
    op.create_table(
        "life_event_conditions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("life_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("comparator", sa.String(), nullable=False),
        sa.Column("threshold_minor", sa.BigInteger(), nullable=True),
        sa.Column("threshold_number", sa.Float(), nullable=True),
        sa.Column("threshold_date", sa.Date(), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("metric IN ('net_worth', 'free_cash', 'account_balance', 'capsule_claim', 'goal_progress', 'member_age', 'date_reached')", name="ck_life_event_conditions_metric"),
        sa.CheckConstraint("comparator IN ('gte', 'lte', 'eq')", name="ck_life_event_conditions_comparator"),
    )
    op.create_index("ix_life_event_conditions_life_event_id", "life_event_conditions", ["life_event_id"])


def downgrade():
    op.drop_table("life_event_conditions")
    op.drop_table("household_members")
    op.drop_constraint("ck_life_events_condition_mode", "life_events", type_="check")
    op.drop_column("life_events", "condition_mode")
