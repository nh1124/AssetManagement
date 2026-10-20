"""積立設定 records get a kind and a schedule; monthly withdrawals become life-event withdrawals (WP23).

kind: contribution (積立), transfer (口座振替), withdrawal (ライフイベントへの取り崩し). amount_minor
is never negative; the schedule is start_period, interval_months (null once, 1 monthly,
12 yearly), and repeat_count or end_period. Records now add up instead of a later record
replacing an earlier one, so a monthly record ends the month before the account's next
record. A record naming a life event withdraws once (partial when the account holds less).
A negative monthly record (毎月の取り崩し, retired) becomes an expense life event of the same
scenario -- named after its note, or 取り崩し（account） -- of the whole amount, and a monthly
withdrawal toward it until the account's next record or the end of the scenario's horizon;
a yield it named stays on a ¥0 contribution of the same month. The per-month unique
indexes go: several records may start in the same month.

Revision ID: 20261021_0083
Revises: 20261020_0082
"""
from datetime import date, datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "20261021_0083"
down_revision = "20261020_0082"
branch_labels = None
depends_on = None


def _index(period: str) -> int:
    year, month = (int(part) for part in period.split("-"))
    return year * 12 + month - 1


def _period(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default="contribution"))
        batch.add_column(sa.Column("to_account_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("amount_minor", sa.BigInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("interval_months", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("repeat_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("end_period", sa.String(7), nullable=True))
        batch.add_column(sa.Column("on_shortage", sa.String(16), nullable=True))
        batch.create_foreign_key("fk_scenario_contribution_plans_to_account", "accounts", ["to_account_id"], ["id"], ondelete="CASCADE")
    op.drop_index("uq_scenario_contribution_plans_event", table_name="scenario_contribution_plans")
    op.drop_index("uq_scenario_contribution_plans_month", table_name="scenario_contribution_plans")

    today = date.today()
    now_index = today.year * 12 + today.month - 1
    rows = bind.execute(sa.text(
        "SELECT p.id, p.scenario_id, p.account_id, p.start_period, p.monthly_amount_minor, p.annual_return, p.note, p.life_event_id, "
        "s.client_id, s.horizon_years, a.name FROM scenario_contribution_plans p JOIN life_scenarios s ON s.id = p.scenario_id "
        "LEFT JOIN accounts a ON a.id = p.account_id ORDER BY p.scenario_id, p.account_id, p.start_period, p.id"
    )).all()
    counts = {"event_withdrawals": 0, "contributions": 0, "ended": 0, "monthly_withdrawals_to_events": 0}
    starts: dict[tuple[int, int], list[str]] = {}
    for row in rows:
        if row.life_event_id is None:
            starts.setdefault((row.scenario_id, row.account_id), []).append(row.start_period)
    for row in rows:
        if row.life_event_id is not None:
            bind.execute(sa.text("UPDATE scenario_contribution_plans SET kind = 'withdrawal', amount_minor = :amount, on_shortage = 'partial', "
                                 "annual_return = NULL WHERE id = :id"), {"amount": -row.monthly_amount_minor, "id": row.id})
            counts["event_withdrawals"] += 1
            continue
        later = [start for start in starts[(row.scenario_id, row.account_id)] if start > row.start_period]
        end = _period(_index(later[0]) - 1) if later else None
        if row.monthly_amount_minor >= 0:
            bind.execute(sa.text("UPDATE scenario_contribution_plans SET kind = 'contribution', amount_minor = :amount, interval_months = 1, "
                                 "end_period = :end WHERE id = :id"), {"amount": row.monthly_amount_minor, "end": end, "id": row.id})
            counts["contributions"] += 1
            counts["ended"] += end is not None
            continue
        last = _index(end) if end is not None else now_index + 12 * (row.horizon_years or 30)
        times = max(1, last - _index(row.start_period) + 1)
        monthly = -row.monthly_amount_minor
        bind.execute(sa.text(
            "INSERT INTO life_events (client_id, scenario_id, lineage, name, target_date, target_amount_minor, priority, note, "
            "condition_mode, direction, created_at) VALUES (:client_id, :scenario_id, :lineage, :name, :when, :amount, 2, :note, "
            "'all', 'expense', :now)"
        ), {"client_id": row.client_id, "scenario_id": row.scenario_id, "lineage": str(uuid4()),
            "name": row.note or f"取り崩し（{row.name or row.account_id}）", "when": date(int(row.start_period[:4]), int(row.start_period[5:]), 1),
            "amount": monthly * times, "note": "毎月の取り崩しから作成（WP23）", "now": datetime.utcnow()})
        event_id = bind.execute(sa.text("SELECT MAX(id) FROM life_events WHERE scenario_id = :scenario_id"), {"scenario_id": row.scenario_id}).scalar()
        bind.execute(sa.text("UPDATE scenario_contribution_plans SET kind = 'withdrawal', amount_minor = :amount, interval_months = 1, "
                             "repeat_count = :times, on_shortage = 'partial', life_event_id = :event_id, annual_return = NULL WHERE id = :id"),
                     {"amount": monthly, "times": times, "event_id": event_id, "id": row.id})
        if row.annual_return is not None:
            bind.execute(sa.text("INSERT INTO scenario_contribution_plans (scenario_id, kind, account_id, start_period, amount_minor, "
                                 "interval_months, end_period, annual_return, monthly_amount_minor) VALUES (:scenario_id, 'contribution', "
                                 ":account_id, :start, 0, 1, :end, :rate, 0)"),
                         {"scenario_id": row.scenario_id, "account_id": row.account_id, "start": row.start_period, "end": end, "rate": row.annual_return})
        counts["monthly_withdrawals_to_events"] += 1
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.drop_column("monthly_amount_minor")
        batch.create_check_constraint("ck_scenario_contribution_plans_kind", "kind IN ('contribution', 'transfer', 'withdrawal')")
        batch.create_check_constraint("ck_scenario_contribution_plans_on_shortage", "on_shortage IS NULL OR on_shortage IN ('skip', 'partial')")
    print("WP23 migration counts:", counts)


def downgrade():
    bind = op.get_bind()
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.drop_constraint("ck_scenario_contribution_plans_kind", type_="check")
        batch.drop_constraint("ck_scenario_contribution_plans_on_shortage", type_="check")
        batch.add_column(sa.Column("monthly_amount_minor", sa.BigInteger(), nullable=False, server_default="0"))
    # Transfers cannot be written the old way. A repeated withdrawal becomes the old monthly withdrawal.
    bind.execute(sa.text("DELETE FROM scenario_contribution_plans WHERE kind = 'transfer'"))
    rows = bind.execute(sa.text(
        "SELECT id, scenario_id, account_id, start_period, amount_minor, kind, interval_months, repeat_count, end_period FROM scenario_contribution_plans "
        "ORDER BY id")).all()
    for row in rows:
        repeated = row.kind == "withdrawal" and row.interval_months is not None
        amount = row.amount_minor if row.kind == "contribution" else -row.amount_minor
        bind.execute(sa.text("UPDATE scenario_contribution_plans SET monthly_amount_minor = :amount"
                             + (", life_event_id = NULL" if repeated else "") + " WHERE id = :id"), {"amount": amount, "id": row.id})
        last = row.end_period
        if row.interval_months is not None and row.repeat_count is not None:
            counted = _period(_index(row.start_period) + row.interval_months * (row.repeat_count - 1))
            last = counted if last is None or counted < last else last
        taken = last is not None and bind.execute(sa.text(
            "SELECT 1 FROM scenario_contribution_plans WHERE scenario_id = :scenario_id AND account_id = :account_id AND start_period = :start "
            "AND kind <> 'withdrawal'"), {"scenario_id": row.scenario_id, "account_id": row.account_id, "start": _period(_index(last) + 1)}).first()
        if (row.kind == "contribution" or repeated) and last is not None and not taken:
            bind.execute(sa.text("INSERT INTO scenario_contribution_plans (scenario_id, kind, account_id, start_period, amount_minor, monthly_amount_minor) "
                                 "VALUES (:scenario_id, 'contribution', :account_id, :start, 0, 0)"),
                         {"scenario_id": row.scenario_id, "account_id": row.account_id, "start": _period(_index(last) + 1)})
    # One record per account and month (and event) again: records that added up become one of their sum.
    groups: dict[tuple, list] = {}
    for row in bind.execute(sa.text(
            "SELECT id, scenario_id, account_id, start_period, life_event_id, monthly_amount_minor, annual_return FROM scenario_contribution_plans "
            "ORDER BY id")).all():
        groups.setdefault((row.scenario_id, row.account_id, row.start_period, row.life_event_id), []).append(row)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rate = next((row.annual_return for row in reversed(rows) if row.annual_return is not None), None)
        bind.execute(sa.text("UPDATE scenario_contribution_plans SET monthly_amount_minor = :amount, annual_return = :rate WHERE id = :id"),
                     {"amount": sum(row.monthly_amount_minor for row in rows), "rate": rate, "id": rows[-1].id})
        for row in rows[:-1]:
            bind.execute(sa.text("DELETE FROM scenario_contribution_plans WHERE id = :id"), {"id": row.id})
    with op.batch_alter_table("scenario_contribution_plans") as batch:
        batch.drop_constraint("fk_scenario_contribution_plans_to_account", type_="foreignkey")
        for column in ("kind", "to_account_id", "amount_minor", "interval_months", "repeat_count", "end_period", "on_shortage"):
            batch.drop_column(column)
    op.create_index("uq_scenario_contribution_plans_month", "scenario_contribution_plans", ["scenario_id", "account_id", "start_period"],
                    unique=True, postgresql_where=sa.text("life_event_id IS NULL"), sqlite_where=sa.text("life_event_id IS NULL"))
    op.create_index("uq_scenario_contribution_plans_event", "scenario_contribution_plans",
                    ["scenario_id", "account_id", "start_period", "life_event_id"], unique=True,
                    postgresql_where=sa.text("life_event_id IS NOT NULL"), sqlite_where=sa.text("life_event_id IS NOT NULL"))
