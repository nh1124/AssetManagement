"""Settlement forecasts use the selected plan's remaining card spending."""

from datetime import date

import pytest

from test_credit_settlement_posted_recurring import (
    BudgetContext, budget_actuals, card_plan, credit_settlement_plan_lines,
    models, process_transaction, _plan, _post,
)


def test_unposted_card_plan_sets_next_month_settlement(card_plan):
    db, card, subs = card_plan
    _plan(db, card, subs)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]
    assert line["suggested_amount"] == 5000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]


def test_partial_posting_reports_posted_and_remaining(card_plan):
    db, card, subs = card_plan
    _plan(db, card, subs)
    _post(db, card, subs, 2000)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]
    assert line["suggested_amount"] == 5000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]
    assert line["suggested_items"][0]["posted_amount"] == 2000
    assert line["suggested_items"][0]["planned_remaining"] == 3000


def test_posted_charge_without_plan_still_settles(card_plan):
    db, card, subs = card_plan
    _post(db, card, subs, 2000)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]
    assert line["suggested_amount"] == 2000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]


def test_bank_funded_plan_is_ignored(card_plan):
    db, card, subs = card_plan
    bank = models.Account(client_id=1, name="bank", account_type="asset", balance=0)
    db.add(bank)
    db.flush()
    _plan(db, bank, subs)
    _post(db, card, subs, 2000)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]
    assert line["suggested_amount"] == 2000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]
    assert line["suggested_items"][0]["planned_remaining"] == 0


def test_settlement_memo_is_scoped_to_plan(card_plan):
    db, card, subs = card_plan
    default = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
    other = models.BudgetPlan(client_id=1, name="Other", is_default=False)
    db.add_all([default, other])
    db.flush()
    _plan(db, card, subs, 5000, default.id)
    _plan(db, card, subs, 9000, other.id)
    db.commit()
    ctx = BudgetContext(db, 1)
    line = credit_settlement_plan_lines(ctx, "2026-11", plan_id=default.id)[0]
    assert line["suggested_amount"] == 5000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]
    line = credit_settlement_plan_lines(ctx, "2026-11", plan_id=other.id)[0]
    assert line["suggested_amount"] == 9000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]
    line = credit_settlement_plan_lines(ctx, "2026-11")[0]
    assert line["suggested_amount"] == 5000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]


@pytest.mark.parametrize("offset, period", [(0, "2026-10"), (1, "2026-11")])
def test_statement_month_follows_payment_offset(card_plan, offset, period):
    db, card, subs = card_plan
    card.liability_payment_month_offset = offset
    _plan(db, card, subs)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), period)[0]
    assert line["suggested_amount"] == 5000
    item = line["suggested_items"][0]
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]


def test_past_statement_fully_posted_plan_is_counted_once(card_plan, monkeypatch):
    db, card, subs = card_plan
    monkeypatch.setattr(budget_actuals, "current_period_key", lambda: "2026-12")
    _plan(db, card, subs, 5000)
    _post(db, card, subs, 5000)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]
    assert line["suggested_amount"] == 5000
    item = line["suggested_items"][0]
    assert item["posted_amount"] == 5000
    assert item["planned_remaining"] == 0
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]


def test_past_statement_partial_posting_leaves_only_remaining(card_plan, monkeypatch):
    db, card, subs = card_plan
    monkeypatch.setattr(budget_actuals, "current_period_key", lambda: "2026-12")
    _plan(db, card, subs, 5000)
    _post(db, card, subs, 2000)
    db.commit()
    line = credit_settlement_plan_lines(BudgetContext(db, 1), "2026-11")[0]
    assert line["suggested_amount"] == 5000
    item = line["suggested_items"][0]
    assert item["posted_amount"] == 2000
    assert item["planned_remaining"] == 3000
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]


def test_capsule_allocation_subtracts_month_movement_not_balance(card_plan, monkeypatch):
    db, card, _ = card_plan
    monkeypatch.setattr(budget_actuals, "current_period_key", lambda: "2026-12")
    investment = models.Account(client_id=1, name="investment", account_type="asset", balance=20000)
    db.add(investment)
    db.flush()
    capsule = models.Capsule(client_id=1, name="reserve", account_id=investment.id, current_balance=20000)
    db.add(capsule)
    db.flush()
    db.add(models.CapsuleHolding(capsule_id=capsule.id, account_id=investment.id, held_amount=20000))
    plan = models.MonthlyPlanLine(
        client_id=1, target_period="2026-10", line_type="allocation",
        target_type="capsule", target_id=capsule.id, account_id=None,
        source_account_id=card.id, name="reserve", amount=4000, is_active=True,
    )
    tx = models.Transaction(client_id=1, date=date(2026, 10, 11), description="investment", amount=4000, currency="JPY")
    db.add_all([plan, tx])
    db.flush()
    process_transaction(db, tx, from_account_id=card.id, to_account_id=investment.id)
    db.commit()
    ctx = BudgetContext(db, 1)
    assert budget_actuals.actual_for_plan_line(ctx, plan, "2026-10") > 4000
    assert budget_actuals.posted_amount_for_plan_line(ctx, plan, "2026-10") == 4000
    line = credit_settlement_plan_lines(ctx, "2026-11")[0]
    assert line["suggested_amount"] == 4000
    item = line["suggested_items"][0]
    assert item["posted_amount"] == 4000
    assert item["planned_remaining"] == 0
    assert item["posted_amount"] + item["planned_remaining"] == line["suggested_amount"]
