"""A transfer into an account and the earmarks set aside in it are not counted on top of each other."""
from datetime import date

from app import models
from app.services.budget_lines import counted_amount, earmark_counted_shares
from app.services.budget_plan_service import get_budget_summary
from app.services.budget_plan_store import create_plan_lines, resolve_budget_plan_id, update_plan_lines
from app.services.money_storage import to_minor
from app.services import contribution_plan_service as plans, goal_service
from app.workflows import goal_budget_workflow
from app import schemas
from scenario_fixtures import account, db  # noqa: F401

TODAY = date.today()
PERIOD = TODAY.strftime("%Y-%m")


def months_ahead(months: int) -> date:
    index = TODAY.year * 12 + TODAY.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def test_an_account_counts_the_larger_of_its_transfers_and_its_earmarks():
    rows = [{"line_type": "allocation", "target_type": "account", "account_id": 1, "amount": 50000},
            {"line_type": "allocation", "target_type": "capsule", "account_id": 1, "amount": 20000},
            {"line_type": "allocation", "target_type": "capsule", "account_id": 1, "amount": 40000},
            {"line_type": "allocation", "target_type": "capsule", "account_id": 2, "amount": 30000}]
    shares = earmark_counted_shares(rows, lambda row: row["amount"])
    # Account 1: 60000 earmarked, 50000 transferred in: only 10000 of the earmarks counts. Account 2 receives nothing.
    assert sum(counted_amount(row, row["amount"], shares) for row in rows) == 50000 + 10000 + 30000
    assert shares == {1: 10000 / 60000, 2: 1.0}


def test_the_plan_summary_does_not_add_an_earmark_to_the_transfer_that_funds_it(db):
    savings, bank = account(db, "貯蓄"), account(db, "銀行")
    capsule = models.Capsule(client_id=1, name="旅行", target_amount_minor=300000, monthly_contribution_minor=0,
                             funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=savings.id, target_amount_minor=300000)])
    db.add(capsule)
    db.commit()
    plan_id = resolve_budget_plan_id(db, 1)
    transfer, earmark = create_plan_lines(db, 1, [
        {"plan_id": plan_id, "target_period": PERIOD, "line_type": "allocation", "target_type": "account", "account_id": savings.id,
         "source_account_id": bank.id, "amount": 50000, "source": "manual", "source_kind": "manual"},
        {"plan_id": plan_id, "target_period": PERIOD, "line_type": "allocation", "target_type": "capsule", "target_id": capsule.id,
         "account_id": savings.id, "amount": 30000},
    ])
    summary = get_budget_summary(db, 1, PERIOD, cash_flow_months=1)
    assert (summary["total_allocation_plan"], summary["total_capsule_plan"]) == (50000, 30000)
    # Earmarks beyond the transfer are set aside from the balance and count for the excess.
    update_plan_lines(db, 1, [{"id": earmark.id, "amount": 70000}])
    summary = get_budget_summary(db, 1, PERIOD, cash_flow_months=1)
    assert (summary["total_allocation_plan"], summary["total_capsule_plan"]) == (70000, 70000)
    assert transfer.id


def test_the_summary_takes_the_shares_on_the_amounts_it_adds_up(db):
    savings, bank = account(db, "貯蓄"), account(db, "銀行")
    capsule = models.Capsule(client_id=1, name="旅行", target_amount_minor=300000, monthly_contribution_minor=0,
                             funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=savings.id, target_amount_minor=300000)])
    db.add(capsule)
    # An automatic transfer with no saved row: its budget is 50000, but the summary's totals add saved amounts (0 here).
    db.add(models.RegistryEntry(client_id=1, name="貯蓄への振替", amount_minor=to_minor(50000, "JPY"), currency="JPY", frequency="Monthly",
                                source_account_id=bank.id, destination_account_id=savings.id, budget_account_id=savings.id,
                                budget_active=True, is_active=True, kind="transfer", start_date=date(2026, 1, 1), repeat_mode="indefinite"))
    db.commit()
    create_plan_lines(db, 1, [{"plan_id": resolve_budget_plan_id(db, 1), "target_period": PERIOD, "line_type": "allocation",
                               "target_type": "capsule", "target_id": capsule.id, "account_id": savings.id, "amount": 30000}])
    summary = get_budget_summary(db, 1, PERIOD, cash_flow_months=1)
    transfer = next(line for line in summary["plan_lines"] if line.get("source") == "registry" and line.get("account_id") == savings.id)
    assert (transfer["amount"], transfer["budget_amount"]) == (0, 50000)
    # Shares taken on the budget amounts would drop the earmark from a total that never counted the transfer.
    assert (summary["total_allocation_plan"], summary["total_capsule_plan"]) == (30000, 30000)


def test_the_goal_plan_warns_when_transfers_alone_exceed_the_contribution(db):
    scenario = models.LifeScenario(client_id=1, name="ゴール", is_goal=True, annual_return=0, inflation=0, horizon_years=3)
    db.add(scenario)
    db.commit()
    savings = account(db, "貯蓄")
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": PERIOD, "monthly_amount": 30000})
    event = goal_service.create_goal_record(db, 1, schemas.LifeEventCreate(
        scenario_id=scenario.id, name="家電", target_amount=120000, target_date=months_ahead(12)))
    plans.create_plan(db, 1, scenario.id, {"account_id": savings.id, "start_period": months_ahead(12).strftime("%Y-%m"),
                                            "monthly_amount": -120000, "life_event_id": event.id})
    create_plan_lines(db, 1, [{"plan_id": resolve_budget_plan_id(db, 1), "target_period": PERIOD, "line_type": "allocation",
                               "target_type": "account", "account_id": savings.id, "amount": 40000, "source": "manual", "source_kind": "manual"}])
    preview = goal_budget_workflow.preview(db, 1, PERIOD, PERIOD)
    # The transfer already brings more than the contribution, so no account row; the earmark sits inside it.
    assert {(row["kind"], row["new"]) for row in preview["changes"]} == {("capsule", 10000)}
    assert preview["warnings"] == [f"{PERIOD}：「貯蓄」は既存の振替（自動取引など）¥40,000が積立設定の月額¥30,000を超えています。"]
