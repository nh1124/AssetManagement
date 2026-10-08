"""Card and liability settlement lines for a month.

A credit expense does not move cash when it happens, it moves cash when the
card is settled. These lines reconstruct that: non-cash activity -- past
transactions and recurring definitions alike -- is allocated to the
settlement period each account's closing day, payment offset and installment
policy imply, then turned into a debt_payment suggestion for that period.
"""
from __future__ import annotations

from .. import models
from .budget_actuals import cash_flow_actual_for_plan_line
from .budget_context import BudgetContext
from .budget_lines import NON_CASH_TRANSACTION_TYPES
from .fx_service import calculate_account_valued_balance, convert_amount, convert_transaction_amount
from .liability_schedule import (
    _account_has_liability_schedule,
    _apply_liability_payment_policy,
    _liability_activity_allocations,
    _recurring_activity_date,
    _recurring_applies_to_period,
)
from .periods import add_months, period_months_between, period_to_range


def _credit_settlement_plan_line(
    ctx: BudgetContext,
    account: models.Account,
    period: str,
    amount: float,
) -> dict:
    policy = account.liability_payment_policy or "full"
    line = {
        "id": None,
        "target_period": period,
        "line_type": "debt_payment",
        "target_type": "account",
        "target_id": account.id,
        "account_id": account.id,
        "source_account_id": None,
        "name": f"{account.name} payment",
        "target_name": account.name,
        "account_name": account.name,
        "amount": 0.0,
        "actual": 0.0,
        "variance": 0.0,
        "recurring_amount": 0.0,
        "suggested_amount": round(amount, 0),
        "suggested_source": "credit_settlement",
        "suggested_items": [{
            "id": account.id,
            "name": account.name,
            "amount": round(amount, 0),
            "source": "credit_settlement",
            "payment_policy": policy,
            "closing_day": account.liability_closing_day,
            "payment_day": account.liability_payment_day,
            "payment_month_offset": account.liability_payment_month_offset or 0,
        }],
        "suggested_status": "missing",
        "source": "credit_settlement",
        "source_kind": "credit_settlement",
        "source_id": account.id,
        "identity_key": "",
        "manual_override": False,
        "cash_treatment": "cash",
        "recurring_transaction_id": None,
        "sync_status": "missing",
        "is_active": True,
    }
    actual = cash_flow_actual_for_plan_line(ctx, line, period)
    line["actual"] = round(actual, 0)
    line["variance"] = round(amount - actual, 0)
    return line


def credit_settlement_plan_lines(ctx: BudgetContext, period: str) -> list[dict]:
    return ctx.credit_settlement_lines(period, lambda: _build_credit_settlement_plan_lines(ctx, period))


def _build_credit_settlement_plan_lines(ctx: BudgetContext, period: str) -> list[dict]:
    accounts_by_id = {
        account_id: account
        for account_id, account in ctx.accounts.items()
        if account.account_type == "liability" and account.is_active
    }
    if not accounts_by_id:
        return []

    max_offset = max((account.liability_payment_month_offset or 0) for account in accounts_by_id.values())
    max_installment_months = max((account.liability_installment_months or 1) for account in accounts_by_id.values())
    search_start_period = add_months(period, -(max_offset + max_installment_months + 1))
    search_start, _ = period_to_range(search_start_period)
    _, search_end = period_to_range(period)
    txs = ctx.db.query(models.Transaction).filter(
        models.Transaction.client_id == ctx.client_id,
        models.Transaction.date >= search_start,
        models.Transaction.date < search_end,
        models.Transaction.type.in_(NON_CASH_TRANSACTION_TYPES),
    ).all()
    credit_usage_by_account: dict[int, float] = {}
    for tx in txs:
        if tx.type not in NON_CASH_TRANSACTION_TYPES or not tx.from_account_id:
            continue
        account = accounts_by_id.get(tx.from_account_id)
        if not account:
            continue
        tx_amount = convert_transaction_amount(ctx.db, tx, client_id=ctx.client_id)
        for settlement_period, amount in _liability_activity_allocations(account, tx.date, tx_amount):
            if settlement_period == period:
                credit_usage_by_account[tx.from_account_id] = credit_usage_by_account.get(tx.from_account_id, 0.0) + amount

    recurring_credit_by_account: dict[int, float] = {}
    recurring_rows = ctx.db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == ctx.client_id,
        models.RecurringTransaction.is_active.is_(True),
        models.RecurringTransaction.type.in_(NON_CASH_TRANSACTION_TYPES),
    ).all()
    for row in recurring_rows:
        if not row.from_account_id:
            continue
        account = accounts_by_id.get(row.from_account_id)
        if not account:
            continue
        for activity_period in period_months_between(search_start_period, period):
            if not _recurring_applies_to_period(row, activity_period):
                continue
            activity_date = _recurring_activity_date(row, activity_period)
            recurring_amount = convert_amount(ctx.db, ctx.client_id, row.amount or 0.0, row.currency or "JPY", as_of_date=activity_date)
            for settlement_period, amount in _liability_activity_allocations(account, activity_date, recurring_amount):
                if settlement_period == period:
                    recurring_credit_by_account[row.from_account_id] = (
                        recurring_credit_by_account.get(row.from_account_id, 0.0)
                        + amount
                    )
    account_ids = set(credit_usage_by_account) | set(recurring_credit_by_account)
    if not account_ids:
        return []

    result = []
    for account_id in account_ids:
        account = accounts_by_id.get(account_id)
        if not account:
            continue
        balance = max(0.0, calculate_account_valued_balance(ctx.db, account))
        activity_amount = credit_usage_by_account.get(account.id, 0.0) + recurring_credit_by_account.get(account.id, 0.0)
        if _account_has_liability_schedule(account):
            raw_amount = activity_amount if activity_amount > 0 else (balance if (account.liability_payment_month_offset or 0) == 0 else 0.0)
        else:
            raw_amount = max(balance, activity_amount)
        amount = _apply_liability_payment_policy(account, raw_amount)
        if amount > 0:
            result.append(_credit_settlement_plan_line(ctx, account, period, amount))
    return result


def _merge_credit_settlement_lines(plan_lines: list[dict], settlement_lines: list[dict]) -> list[dict]:
    for settlement in settlement_lines:
        matched = next(
            (
                line for line in plan_lines
                if line.get("line_type") == "debt_payment"
                and line.get("account_id") == settlement.get("account_id")
            ),
            None,
        )
        if not matched:
            plan_lines.append(settlement)
            continue
        suggested = round(settlement.get("suggested_amount") or 0.0, 0)
        matched["suggested_amount"] = suggested
        matched["suggested_source"] = "credit_settlement"
        matched["suggested_items"] = settlement.get("suggested_items", [])
        matched["suggested_status"] = (
            "synced"
            if round(matched.get("amount") or 0.0, 0) == suggested
            else "diff"
        )
        if matched.get("source") != "manual":
            matched["source_kind"] = matched.get("source_kind") or "credit_settlement"
            matched["source_id"] = matched.get("source_id") or settlement.get("source_id")
        matched["sync_status"] = matched["suggested_status"]
    return plan_lines
