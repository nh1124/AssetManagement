"""Goals v2: loans in life events, withdrawals in contribution plans, goal-derived earmarks.

- life_events: kinds borrowing and repayment, interest_rate, borrowing_event_id,
  repeat_count; account_id keeps only asset accounts (the event's account).
- scenario_contribution_plans: a negative monthly amount is a withdrawal.
- capsules.goal_event_id: the earmark made for a goal event. Each earmark linked to an
  event in goal_event_earmarks takes its first linked event; the old table itself is
  dropped later with the other retired tables.

Revision ID: 20261019_0079
Revises: 20261019_0078
"""
from alembic import op
import sqlalchemy as sa

revision = "20261019_0079"
down_revision = "20261019_0078"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table("life_events") as batch:
        batch.drop_constraint("ck_life_events_direction", type_="check")
        batch.create_check_constraint("ck_life_events_direction", "direction IN ('expense', 'income', 'borrowing', 'repayment')")
        batch.add_column(sa.Column("interest_rate", sa.Float(), nullable=True))
        batch.add_column(sa.Column("borrowing_event_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("repeat_count", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_life_events_borrowing_event", "life_events", ["borrowing_event_id"], ["id"], ondelete="SET NULL")
    # An event's account is now the asset account it works through; a subject means nothing here.
    cleared = bind.execute(sa.text(
        "UPDATE life_events SET account_id = NULL WHERE account_id IS NOT NULL AND account_id NOT IN "
        "(SELECT id FROM accounts WHERE account_type = 'asset')"
    )).rowcount
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.drop_constraint("ck_scenario_contribution_plans_amount", type_="check")
    with op.batch_alter_table("capsules") as batch:
        batch.add_column(sa.Column("goal_event_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_capsules_goal_event", "life_events", ["goal_event_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_capsules_goal_event_id", ["goal_event_id"])
    linked = bind.execute(sa.text(
        "UPDATE capsules SET goal_event_id = (SELECT g.life_event_id FROM goal_event_earmarks g "
        "WHERE g.capsule_id = capsules.id AND g.share_bp > 0 ORDER BY g.id LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM goal_event_earmarks g WHERE g.capsule_id = capsules.id AND g.share_bp > 0)"
    )).rowcount
    print(f"WP18 migration counts: {{'event_subjects_cleared': {cleared}, 'earmarks_linked_to_events': {linked}}}")


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM goal_event_earmarks"))
    bind.execute(sa.text(
        "INSERT INTO goal_event_earmarks (client_id, life_event_id, capsule_id, share_bp) "
        "SELECT client_id, goal_event_id, id, 10000 FROM capsules WHERE goal_event_id IS NOT NULL AND client_id IS NOT NULL"
    ))
    with op.batch_alter_table("capsules") as batch:
        batch.drop_index("ix_capsules_goal_event_id")
        batch.drop_constraint("fk_capsules_goal_event", type_="foreignkey")
        batch.drop_column("goal_event_id")
    bind.execute(sa.text("UPDATE scenario_contribution_plans SET monthly_amount_minor = 0 WHERE monthly_amount_minor < 0"))
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.create_check_constraint("ck_scenario_contribution_plans_amount", "monthly_amount_minor >= 0")
    bind.execute(sa.text("DELETE FROM life_events WHERE direction IN ('borrowing', 'repayment')"))
    with op.batch_alter_table("life_events") as batch:
        batch.drop_constraint("fk_life_events_borrowing_event", type_="foreignkey")
        batch.drop_column("repeat_count")
        batch.drop_column("borrowing_event_id")
        batch.drop_column("interest_rate")
        batch.drop_constraint("ck_life_events_direction", type_="check")
        batch.create_check_constraint("ck_life_events_direction", "direction IN ('expense', 'income')")
