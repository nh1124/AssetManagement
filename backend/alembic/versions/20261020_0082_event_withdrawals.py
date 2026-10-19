"""What an account gives toward a life event becomes a 積立設定 record (WP22).

scenario_contribution_plans.life_event_id: a record naming an event takes its amount out
of the account once, in its month, for that event (ライフイベントへの取り崩し). Each WP21
share of an expense event becomes such a record in the event's month for its share of
the target; shares of other kinds are dropped (they go through the residual net worth).
Then life_event_fundings is dropped. A monthly record stays unique per account and
month; event records are unique per account, month and event.

Revision ID: 20261020_0082
Revises: 20261020_0081
"""
from alembic import op
import sqlalchemy as sa

revision = "20261020_0082"
down_revision = "20261020_0081"
branch_labels = None
depends_on = None


def _month(value) -> str:
    return str(value)[:7]


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.add_column(sa.Column("life_event_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_scenario_contribution_plans_life_event", "life_events", ["life_event_id"], ["id"], ondelete="CASCADE")
        batch.drop_constraint("uq_scenario_contribution_plans_month", type_="unique")
    op.create_index("ix_scenario_contribution_plans_life_event_id", "scenario_contribution_plans", ["life_event_id"])
    op.create_index("uq_scenario_contribution_plans_month", "scenario_contribution_plans", ["scenario_id", "account_id", "start_period"],
                    unique=True, postgresql_where=sa.text("life_event_id IS NULL"), sqlite_where=sa.text("life_event_id IS NULL"))
    op.create_index("uq_scenario_contribution_plans_event", "scenario_contribution_plans",
                    ["scenario_id", "account_id", "start_period", "life_event_id"], unique=True,
                    postgresql_where=sa.text("life_event_id IS NOT NULL"), sqlite_where=sa.text("life_event_id IS NOT NULL"))
    rows = bind.execute(sa.text(
        "SELECT e.id, e.scenario_id, e.target_date, e.target_amount_minor, f.account_id, f.share_bp FROM life_event_fundings f "
        "JOIN life_events e ON e.id = f.life_event_id WHERE e.direction = 'expense' AND e.target_date IS NOT NULL ORDER BY f.id"
    )).all()
    moved = 0
    for event_id, scenario_id, target_date, target_minor, account_id, share_bp in rows:
        amount = (target_minor or 0) * share_bp // 10000
        if amount <= 0:
            continue
        bind.execute(sa.text(
            "INSERT INTO scenario_contribution_plans (scenario_id, account_id, start_period, monthly_amount_minor, life_event_id) "
            "VALUES (:scenario_id, :account_id, :period, :amount, :event_id)"
        ), {"scenario_id": scenario_id, "account_id": account_id, "period": _month(target_date), "amount": -amount, "event_id": event_id})
        moved += 1
    dropped = bind.execute(sa.text("SELECT COUNT(*) FROM life_event_fundings")).scalar() - moved
    op.drop_table("life_event_fundings")
    print("WP22 migration counts:", {"shares_to_records": moved, "shares_dropped": dropped})


def downgrade():
    bind = op.get_bind()
    op.create_table(
        "life_event_fundings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("life_event_id", sa.Integer(), sa.ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("share_bp", sa.Integer(), nullable=False),
        sa.UniqueConstraint("life_event_id", "account_id", name="uq_life_event_fundings_account"),
        sa.CheckConstraint("share_bp > 0 AND share_bp <= 10000", name="ck_life_event_fundings_share"),
    )
    # An event's records from one account become that account's share of its target.
    rows = bind.execute(sa.text(
        "SELECT p.life_event_id, p.account_id, SUM(-p.monthly_amount_minor), MAX(e.target_amount_minor) FROM scenario_contribution_plans p "
        "JOIN life_events e ON e.id = p.life_event_id WHERE p.life_event_id IS NOT NULL GROUP BY p.life_event_id, p.account_id "
        "ORDER BY p.life_event_id, p.account_id"
    )).all()
    totals: dict[int, int] = {}
    for event_id, account_id, amount, target in rows:
        share = max(1, min(10000 - totals.get(event_id, 0), round((amount or 0) * 10000 / target) if target else 10000))
        if share <= 0 or totals.get(event_id, 0) >= 10000:
            continue
        totals[event_id] = totals.get(event_id, 0) + share
        bind.execute(sa.text("INSERT INTO life_event_fundings (life_event_id, account_id, share_bp) VALUES (:event_id, :account_id, :share)"),
                     {"event_id": event_id, "account_id": account_id, "share": share})
    bind.execute(sa.text("DELETE FROM scenario_contribution_plans WHERE life_event_id IS NOT NULL"))
    op.drop_index("uq_scenario_contribution_plans_event", table_name="scenario_contribution_plans")
    op.drop_index("uq_scenario_contribution_plans_month", table_name="scenario_contribution_plans")
    op.drop_index("ix_scenario_contribution_plans_life_event_id", table_name="scenario_contribution_plans")
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.drop_constraint("fk_scenario_contribution_plans_life_event", type_="foreignkey")
        batch.drop_column("life_event_id")
        batch.create_unique_constraint("uq_scenario_contribution_plans_month", ["scenario_id", "account_id", "start_period"])
