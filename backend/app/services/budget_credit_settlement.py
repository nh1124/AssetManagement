"""Card settlement lines for a month.

A card payment does not move cash when it happens, it moves cash when the card
is settled. These lines reconstruct that: activity on a card -- past
transactions allocated by the account's statement schedule and remaining
card-funded plan amounts -- is assigned to the settlement period,
then turned into a debt_payment suggestion for that period.

"Activity on a card" means a credit leg on an account whose liability_kind is
"card". It used to mean a transaction whose type was CreditExpense or
CreditAssetPurchase, which got two things wrong. A card charge recorded with
the wrong type was missed, and a loan drawn down on an installment plan was
treated as a card statement, so the projection proposed clearing the whole
remaining balance in one month even though the repayment schedule was already
modelled as a recurring debt payment. Whether a liability settles on a monthly
cycle belongs to the account, not to each transaction against it.
"""
from __future__ import annotations

from datetime import timedelta

from .. import models
from .budget_actuals import (
    _cash_flow_line_source_account_id,
    cash_flow_actual_for_plan_line,
    posted_amount_for_plan_line,
)
from .budget_context import BudgetContext
from .budget_plan_store import resolve_budget_plan_id
from .fx_service import calculate_account_valued_balance
from .journal_legs import legs_in_range
from .liability_schedule import (
    _account_has_liability_schedule,
    _apply_liability_payment_policy,
    _liability_activity_allocations,
)
from .periods import add_months, period_to_range


def _credit_settlement_plan_line(
    ctx: BudgetContext,
    account: models.Account,
    period: str,
    amount: float,
    posted_amount: float,
    planned_remaining: float,
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
            "posted_amount": round(posted_amount, 0),
            "planned_remaining": round(planned_remaining, 0),
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


def credit_settlement_plan_lines(
    ctx: BudgetContext, period: str, plan_id: int | None = None,
) -> list[dict]:
    plan_id = resolve_budget_plan_id(ctx.db, ctx.client_id, plan_id)
    return ctx.credit_settlement_lines(
        f"{period}:{plan_id}",
        lambda: _build_credit_settlement_plan_lines(ctx, period, plan_id),
    )


def _settling_accounts(ctx: BudgetContext) -> dict[int, models.Account]:
    """Active liability accounts that settle on a monthly cycle."""
    return {
        account_id: account
        for account_id, account in ctx.accounts.items()
        if account.account_type == "liability"
        and account.is_active
        and account.liability_kind == "card"
    }


def _build_credit_settlement_plan_lines(
    ctx: BudgetContext, period: str, plan_id: int | None = None,
) -> list[dict]:
    plan_id = resolve_budget_plan_id(ctx.db, ctx.client_id, plan_id)
    accounts_by_id = _settling_accounts(ctx)
    if not accounts_by_id:
        return []

    max_offset = max((account.liability_payment_month_offset or 0) for account in accounts_by_id.values())
    max_installment_months = max((account.liability_installment_months or 1) for account in accounts_by_id.values())
    search_start_period = add_months(period, -(max_offset + max_installment_months + 1))
    search_start, _ = period_to_range(search_start_period)
    _, search_end = period_to_range(period)
    credit_usage_by_account: dict[int, float] = {}
    for leg in legs_in_range(
        ctx.db,
        ctx.client_id,
        search_start,
        search_end - timedelta(days=1),
        account_ids=set(accounts_by_id),
    ):
        if leg.credit <= 0:
            continue  # a debit on a card is a repayment, not new activity
        account = accounts_by_id[leg.account.id]
        for settlement_period, amount in _liability_activity_allocations(
            account, leg.transaction.date, leg.credit
        ):
            if settlement_period == period:
                credit_usage_by_account[leg.account.id] = (
                    credit_usage_by_account.get(leg.account.id, 0.0) + amount
                )

    plan_remaining_by_account: dict[int, float] = {}
    # Cards sharing a statement month must use the same resolved plan snapshot.
    resolved_by_period: dict[str, list[tuple[models.MonthlyPlanLine, int | None]]] = {}
    for account in accounts_by_id.values():
        statement_period = add_months(period, -(account.liability_payment_month_offset or 0))
        if statement_period not in resolved_by_period:
            plan_rows = ctx.db.query(models.MonthlyPlanLine).filter(
                models.MonthlyPlanLine.client_id == ctx.client_id,
                models.MonthlyPlanLine.target_period == statement_period,
                models.MonthlyPlanLine.plan_id == plan_id,
                models.MonthlyPlanLine.is_active.is_(True),
            ).all()
            resolved_by_period[statement_period] = [
                (line, _cash_flow_line_source_account_id(ctx, line))
                for line in plan_rows
            ]
        for line, source_account_id in resolved_by_period[statement_period]:
            if source_account_id != account.id:
                continue
            # Subtract each line's posted part from its own plan, so only what
            # the plan still expects is added to the ledger activity above.
            remaining = max(
                0.0,
                (line.amount or 0.0) - posted_amount_for_plan_line(ctx, line, statement_period),
            )
            plan_remaining_by_account[account.id] = (
                plan_remaining_by_account.get(account.id, 0.0) + remaining
            )
    account_ids = set(credit_usage_by_account) | set(plan_remaining_by_account)
    if not account_ids:
        return []

    result = []
    for account_id in account_ids:
        account = accounts_by_id.get(account_id)
        if not account:
            continue
        balance = max(0.0, calculate_account_valued_balance(ctx.db, account))
        activity_amount = credit_usage_by_account.get(account.id, 0.0) + plan_remaining_by_account.get(account.id, 0.0)
        if _account_has_liability_schedule(account):
            raw_amount = activity_amount if activity_amount > 0 else (balance if (account.liability_payment_month_offset or 0) == 0 else 0.0)
        else:
            raw_amount = max(balance, activity_amount)
        amount = _apply_liability_payment_policy(account, raw_amount)
        if amount > 0:
            result.append(_credit_settlement_plan_line(
                ctx, account, period, amount,
                credit_usage_by_account.get(account.id, 0.0),
                plan_remaining_by_account.get(account.id, 0.0),
            ))
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
