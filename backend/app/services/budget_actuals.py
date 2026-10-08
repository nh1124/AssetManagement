"""What actually happened against a plan line, and where the money moved.

Two notions of "actual" live here on purpose. actual_for_plan_line answers
budget variance, so a capsule line reports the capsule's balance;
cash_flow_actual_for_plan_line answers cash flow, so the same line reports
only the movement executed in that month. The flow helpers then classify an
amount into asset buckets by looking at the accounts on each side.
"""
from __future__ import annotations

from typing import Iterable

from .. import models
from .budget_context import BudgetContext
from .budget_lines import (
    ASSET_FLOW_BUCKETS,
    _empty_balance,
    _empty_flow,
    _fallback_line_flow,
    _line_attr,
    _line_cash_treatment,
    _movement_flow,
    _plan_match_key,
    account_flow_bucket,
)
from .budget_registry_lines import registry_plan_lines
from .fx_service import convert_transaction_amount
from .periods import current_period_key


def _sum_transactions(ctx: BudgetContext, txs: Iterable[models.Transaction]) -> float:
    return sum(convert_transaction_amount(ctx.db, tx, client_id=ctx.client_id) for tx in txs)


def _funded_by_card(ctx: BudgetContext, line: models.MonthlyPlanLine | dict) -> bool:
    """Whether the account paying for this line settles on a monthly cycle.

    This replaces reading the ledger type of the linked recurring definition.
    A line paid by card does not move cash in its own month; the cash moves
    when the card is settled, and budget_credit_settlement projects that.
    """
    account = ctx.account(_cash_flow_line_source_account_id(ctx, line))
    return bool(account and account.liability_kind == "card")


def plan_line_has_cash_impact(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
) -> bool:
    treatment = _line_cash_treatment(line)
    if treatment == "cash":
        return True
    if treatment == "non_cash":
        return False
    return not _funded_by_card(ctx, line)


def actual_for_plan_line(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
) -> float:
    txs = ctx.period_transactions(period)
    line_type = line["line_type"] if isinstance(line, dict) else line.line_type
    target_type = line["target_type"] if isinstance(line, dict) else line.target_type
    target_id = line.get("target_id") if isinstance(line, dict) else line.target_id
    account_id = line.get("account_id") if isinstance(line, dict) else line.account_id
    name = (line.get("name") if isinstance(line, dict) else line.name) or ""
    needle = name.lower()

    if target_type == "capsule" and target_id:
        capsule = ctx.capsule(target_id)
        if capsule:
            return ctx.capsule_balance(capsule)
        account_id = ctx.capsule_account_ids.get(target_id)

    if line_type == "income":
        selected = [
            tx for tx in txs
            if tx.type == "Income"
            and (
                (account_id and tx.from_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
                or (not account_id and needle and needle in (tx.category or "").lower())
            )
        ]
    elif line_type == "expense":
        selected = [
            tx for tx in txs
            if tx.type in {"Expense", "CreditExpense"}
            and (
                (account_id and tx.to_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
                or (not account_id and needle and needle in (tx.category or "").lower())
            )
        ]
    elif line_type == "allocation":
        selected = [
            tx for tx in txs
            if (
                tx.type in {"Transfer", "CreditAssetPurchase"}
                or tx.type == "Income"
            )
            and (
                (account_id and tx.to_account_id == account_id)
                or (
                    not account_id
                    and needle
                    and (
                        needle in (tx.description or "").lower()
                        or needle in (tx.category or "").lower()
                    )
                )
            )
        ]
    elif line_type == "debt_payment":
        selected = [
            tx for tx in txs
            if tx.type == "LiabilityPayment"
            and (
                (account_id and tx.to_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
            )
        ]
    elif line_type == "borrowing":
        selected = [
            tx for tx in txs
            if tx.type == "Borrowing"
            and (
                (account_id and tx.from_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
            )
        ]
    elif line_type == "drawdown":
        selected = [
            tx for tx in txs
            if tx.type == "Transfer"
            and (
                (account_id and tx.from_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
            )
        ]
    else:
        selected = []
    return _sum_transactions(ctx, selected)


def cash_flow_actual_for_plan_line(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
) -> float:
    """Return transactions already executed for a plan line in a cash-flow period.

    This intentionally differs from actual_for_plan_line: capsule budget rows use
    current capsule balance for budget variance, but cash flow only needs the
    already-executed movement for the month.
    """
    if not plan_line_has_cash_impact(ctx, line):
        return 0.0
    txs = ctx.period_transactions(period)
    line_type = _line_attr(line, "line_type")
    account_id = _cash_flow_line_account_id(ctx, line)
    source_account_id = _cash_flow_line_source_account_id(ctx, line)
    name = (_line_attr(line, "name") or "").lower()

    def source_matches(tx: models.Transaction, attr: str) -> bool:
        return not source_account_id or getattr(tx, attr) == source_account_id

    def matches_text(tx: models.Transaction) -> bool:
        return bool(
            name
            and (
                name in (tx.description or "").lower()
                or name in (tx.category or "").lower()
            )
        )

    if line_type == "income":
        selected = [
            tx for tx in txs
            if tx.type == "Income"
            and source_matches(tx, "to_account_id")
            and ((account_id and tx.from_account_id == account_id) or (not account_id and matches_text(tx)))
        ]
    elif line_type == "expense":
        selected = [
            tx for tx in txs
            if tx.type == "Expense"
            and source_matches(tx, "from_account_id")
            and ((account_id and tx.to_account_id == account_id) or (not account_id and matches_text(tx)))
        ]
    elif line_type == "allocation":
        selected = [
            tx for tx in txs
            if (
                (
                    tx.type == "Transfer"
                    and source_matches(tx, "from_account_id")
                    and ((account_id and tx.to_account_id == account_id) or (not account_id and matches_text(tx)))
                )
                or (
                    tx.type == "Income"
                    and ((account_id and tx.to_account_id == account_id) or (not account_id and matches_text(tx)))
                )
            )
        ]
    elif line_type == "debt_payment":
        selected = [
            tx for tx in txs
            if tx.type == "LiabilityPayment"
            and source_matches(tx, "from_account_id")
            and ((account_id and tx.to_account_id == account_id) or (not account_id and matches_text(tx)))
        ]
    elif line_type == "borrowing":
        selected = [
            tx for tx in txs
            if tx.type == "Borrowing"
            and source_matches(tx, "to_account_id")
            and ((account_id and tx.from_account_id == account_id) or (not account_id and matches_text(tx)))
        ]
    elif line_type == "drawdown":
        selected = [
            tx for tx in txs
            if tx.type == "Transfer"
            and source_matches(tx, "to_account_id")
            and ((account_id and tx.from_account_id == account_id) or (not account_id and matches_text(tx)))
        ]
    else:
        selected = []
    return _sum_transactions(ctx, selected)


def _cash_flow_line_account_id(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
) -> int | None:
    account_id = _line_attr(line, "account_id")
    if account_id:
        return account_id

    target_type = _line_attr(line, "target_type")
    target_id = _line_attr(line, "target_id")
    if target_type == "capsule" and target_id:
        capsule = ctx.capsule(target_id)
        return capsule.account_id if capsule else None

    if target_type == "life_event" and target_id:
        capsule = ctx.capsule_for_life_event(target_id)
        return capsule.account_id if capsule else None

    return None


def _registry_line_for_plan_line(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
) -> dict | None:
    period = _line_attr(line, "target_period")
    if not period:
        return None
    line_type = _line_attr(line, "line_type")
    target_type = _line_attr(line, "target_type")
    account_id = _line_attr(line, "account_id")
    name = _line_attr(line, "name") or _line_attr(line, "target_name")
    cash_treatment = _line_attr(line, "cash_treatment") or "auto"
    key = _plan_match_key(line_type, target_type, account_id, name, None, cash_treatment)
    for registry_line in registry_plan_lines(ctx, period):
        registry_key = _plan_match_key(
            registry_line.get("line_type"),
            registry_line.get("target_type"),
            registry_line.get("account_id"),
            registry_line.get("name"),
            None,
            registry_line.get("cash_treatment"),
        )
        if registry_key == key:
            return registry_line

        plan_name = (name or "").strip().lower()
        if plan_name:
            item_names = {
                (item.get("name") or "").strip().lower()
                for item in registry_line.get("registry_items", [])
            }
            if (
                registry_line.get("line_type") == line_type
                and registry_line.get("account_id") == account_id
                and (registry_line.get("cash_treatment") or "auto") == cash_treatment
                and plan_name in item_names
            ):
                return registry_line
    return None


def _cash_flow_line_source_account_id(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
) -> int | None:
    source_account_id = _line_attr(line, "source_account_id")
    if source_account_id:
        return source_account_id
    registry_line = _registry_line_for_plan_line(ctx, line)
    return registry_line.get("source_account_id") if registry_line else None


def _plan_line_movement_accounts(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
) -> tuple[models.Account | None, models.Account | None]:
    line_type = _line_attr(line, "line_type")
    source_account = ctx.account(_cash_flow_line_source_account_id(ctx, line))
    target_account = ctx.account(_cash_flow_line_account_id(ctx, line))

    if line_type == "income":
        return target_account, source_account
    if line_type == "expense":
        return source_account, target_account
    if line_type == "allocation":
        return source_account, target_account
    if line_type == "debt_payment":
        return source_account, target_account
    if line_type == "borrowing":
        return target_account, source_account
    if line_type == "drawdown":
        return target_account, source_account
    return source_account, target_account


def plan_line_flow_for_amount(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    amount: float,
) -> dict[str, float]:
    if amount <= 0:
        return _empty_flow()
    treatment = _line_cash_treatment(line)
    if treatment == "non_cash":
        flow = _empty_flow()
        flow["non_cash_budget"] = amount
        return flow

    from_account, to_account = _plan_line_movement_accounts(ctx, line)
    if from_account or to_account:
        flow = _movement_flow(account_flow_bucket(from_account), account_flow_bucket(to_account), amount)
        has_classified_movement = any(
            abs(flow.get(key, 0.0)) > 0
            for key in (*ASSET_FLOW_BUCKETS, "financing", "internal_transfer", "non_cash_budget")
        )
        if not has_classified_movement and (from_account is None or to_account is None):
            return _fallback_line_flow(_line_attr(line, "line_type"), amount)
        if treatment == "cash" and not any(abs(flow.get(bucket, 0.0)) > 0 for bucket in ASSET_FLOW_BUCKETS):
            return _fallback_line_flow(_line_attr(line, "line_type"), amount)
        return flow
    return _fallback_line_flow(_line_attr(line, "line_type"), amount)


def _balance_movement_for_amount(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    amount: float,
) -> dict[str, float]:
    movement = _empty_balance()
    if amount <= 0:
        return movement

    from_account, to_account = _plan_line_movement_accounts(ctx, line)
    from_bucket = account_flow_bucket(from_account)
    to_bucket = account_flow_bucket(to_account)

    if from_bucket in ASSET_FLOW_BUCKETS:
        movement[from_bucket] -= amount
    elif from_bucket == "liability":
        movement["liabilities"] += amount

    if to_bucket in ASSET_FLOW_BUCKETS:
        movement[to_bucket] += amount
    elif to_bucket == "liability":
        movement["liabilities"] -= amount

    if from_account is None or to_account is None:
        fallback = _fallback_line_flow(_line_attr(line, "line_type"), amount)
        movement["operating"] += fallback["operating"]
        if fallback["financing"] and from_bucket != "liability" and to_bucket != "liability":
            movement["liabilities"] += fallback["financing"]

    return movement


def _projection_amounts_for_period(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
) -> tuple[float, float, float]:
    planned = _line_attr(line, "amount") or 0.0
    if not _line_attr(line, "id") and planned <= 0:
        planned = (
            _line_attr(line, "suggested_amount")
            or _line_attr(line, "registry_amount")
            or _line_attr(line, "recurring_amount")
            or 0.0
        )
    if period != current_period_key():
        return planned, 0.0, planned
    if plan_line_has_cash_impact(ctx, line):
        actual = cash_flow_actual_for_plan_line(ctx, line, period)
    else:
        actual = actual_for_plan_line(ctx, line, period)
    remaining = max(0.0, planned - actual)
    projected = actual + remaining
    return projected, actual, remaining
