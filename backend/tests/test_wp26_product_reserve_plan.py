"""§8-4: making the plan of 物品の取り置き from a base amount, less what the earmark already holds."""
from datetime import date

import pytest

from app import models
from app.domain.errors import Conflict
from app.domain.journal import Leg
from app.services.budget_plan_service import get_budget_summary
from app.services.budget_plan_store import create_plan_lines, resolve_budget_plan_id
from app.services.ledger_service import create_transaction
from app.services.product_reserve_service import refresh_product_capsules
from app.workflows import product_reserve_plan_workflow as workflow
from scenario_fixtures import account, db  # noqa: F401

TODAY = date.today()
FIRST = TODAY.year * 12 + TODAY.month - 1


def period(offset: int) -> str:
    index = FIRST + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_start(offset: int) -> date:
    index = FIRST + offset
    return date(index // 12, index % 12 + 1, 1)


def fridge(db, *, saved=8000, held=30000, sources=True):
    """A ¥120,000 fridge replaced 10 months from this month; the earmark saved ¥8,000 a month and holds ¥30,000."""
    savings = account(db, "貯蓄", balance=100000)
    capsule = models.Capsule(client_id=1, name="家電", target_amount_minor=0, monthly_contribution_minor=0,
                             funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=savings.id, target_amount_minor=120000)] if sources else [])
    db.add(capsule)
    db.flush()
    db.add(models.Product(client_id=1, name="冷蔵庫", is_asset=True, purchase_price_minor=120000, purchase_date=month_start(-2), lifespan_months=12,
                          funding_capsule_id=capsule.id))
    db.flush()
    refresh_product_capsules(db, 1, [capsule.id])
    capsule.monthly_contribution_minor = saved
    db.commit()
    if held:
        create_transaction(db, client_id=1, date=TODAY, description="確保", amount_minor=held, currency="JPY",
                           legs=[Leg(savings.id, debit=held, capsule_id=capsule.id), Leg(savings.id, credit=held)])
        db.commit()
    return savings, capsule


def rows(preview):
    return [change["new"] for change in preview["changes"]]


@pytest.mark.parametrize("base, held, expected", [
    # 取り置きに設定した月額 ¥8,000: the ¥30,000 held comes off the nearest months, or ¥3,000 (over 10 months) from each.
    ("saved", "recent", [0, 0, 0, 2000]),
    ("saved", "even", [5000] * 4),
    # 残り期間に合わせる: ¥120,000 over the 10 months left is ¥12,000.
    ("remaining", "recent", [0, 0, 6000, 12000]),
    ("remaining", "even", [9000] * 4),
])
def test_the_base_and_how_the_held_amount_comes_off(db, base, held, expected):
    savings, capsule = fridge(db)
    preview = workflow.preview(db, 1, period(0), period(3), base, held)
    assert [change["period"] for change in preview["changes"]] == [period(offset) for offset in range(4)]
    assert {(change["capsule_id"], change["account_id"]) for change in preview["changes"]} == {(capsule.id, savings.id)}
    assert rows(preview) == expected
    # Today the plan shows the saved monthly amount.
    assert {change["current"] for change in preview["changes"]} == {8000}
    assert preview["earmarks"] == [{"capsule_id": capsule.id, "name": "家電", "base": 8000 if base == "saved" else 12000,
                                    "held": 30000, "replacement": period(10)}]


def test_apply_writes_the_rows_and_a_zero_row_stands_for_a_month_that_needs_nothing(db):
    savings, capsule = fridge(db)
    preview = workflow.preview(db, 1, period(0), period(3), "saved", "recent")
    assert workflow.apply(db, 1, period(0), period(3), "saved", "recent", preview["fingerprint"])["applied"] == 4
    stored = db.query(models.MonthlyPlanLine).filter_by(client_id=1, target_type="capsule", target_id=capsule.id, is_active=True).order_by(
        models.MonthlyPlanLine.target_period).all()
    assert [(line.target_period, line.account_id, line.amount_minor, line.source_kind) for line in stored] == [
        (period(offset), savings.id, amount, "product_reserve") for offset, amount in enumerate([0, 0, 0, 2000])]
    # The ¥0 row keeps the saved ¥8,000 from standing in for the month.
    lines = [line for line in get_budget_summary(db, 1, period(0))["plan_lines"] if line.get("target_id") == capsule.id]
    assert [(line["id"] is not None, line["budget_amount"]) for line in lines] == [(True, 0)]
    # Made again with nothing changed, nothing is written.
    again = workflow.preview(db, 1, period(0), period(3), "saved", "recent")
    assert not [change for change in again["changes"] if change["changed"]]
    # Another base replaces the rows, whatever wrote them.
    other = workflow.preview(db, 1, period(0), period(3), "remaining", "even")
    workflow.apply(db, 1, period(0), period(3), "remaining", "even", other["fingerprint"])
    assert db.query(models.MonthlyPlanLine).filter_by(target_id=capsule.id, is_active=True).count() == 4
    assert {line.amount_minor for line in db.query(models.MonthlyPlanLine).filter_by(target_id=capsule.id, is_active=True)} == {9000}


def test_a_row_typed_on_the_plan_page_is_replaced_not_doubled(db):
    savings, capsule = fridge(db)
    typed, = create_plan_lines(db, 1, [{"plan_id": resolve_budget_plan_id(db, 1), "target_period": period(0), "line_type": "allocation",
                                        "target_type": "capsule", "target_id": capsule.id, "account_id": savings.id, "amount": 15000,
                                        "source": "capsule", "source_kind": "capsule"}])
    preview = workflow.preview(db, 1, period(0), period(1), "remaining", "even")
    first = preview["changes"][0]
    assert (first["line_id"], first["current"], first["new"]) == (typed.id, 15000, 9000)
    workflow.apply(db, 1, period(0), period(1), "remaining", "even", preview["fingerprint"])
    assert [line.amount_minor for line in db.query(models.MonthlyPlanLine).filter_by(target_id=capsule.id, target_period=period(0), is_active=True)] == [9000]


def test_no_month_after_the_replacement_and_a_changed_preview_is_refused(db):
    savings, capsule = fridge(db, held=0)
    preview = workflow.preview(db, 1, period(0), period(13), "remaining", "even")
    # The fridge is replaced in month 10: months 0-9 are planned.
    assert [change["period"] for change in preview["changes"]] == [period(offset) for offset in range(10)]
    assert set(rows(preview)) == {12000}
    capsule.monthly_contribution_minor = 1
    db.commit()
    stale = workflow.preview(db, 1, period(0), period(1), "saved", "even")
    capsule.monthly_contribution_minor = 2
    db.commit()
    with pytest.raises(Conflict):
        workflow.apply(db, 1, period(0), period(1), "saved", "even", stale["fingerprint"])
    assert db.query(models.MonthlyPlanLine).filter_by(target_id=capsule.id).count() == 0


def test_an_earmark_without_funding_accounts_is_left_out_with_a_warning(db):
    fridge(db, sources=False, held=0)
    preview = workflow.preview(db, 1, period(0), period(1), "saved", "even")
    assert preview["changes"] == []
    assert preview["warnings"] == ["取り置き「家電」は資金元の口座がないため作りません。取り置きの画面で口座を設定してください。"]
