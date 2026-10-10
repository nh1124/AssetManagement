"""What actually happened against a plan line, and where the money moved.

Two notions of "actual" live here on purpose. actual_for_plan_line answers
budget variance, so a capsule line reports the capsule's balance;
cash_flow_actual_for_plan_line answers cash flow, so the same line reports
only the movement executed in that month. The flow helpers then classify an
amount into asset buckets by looking at the accounts on each side.
"""
from __future__ import annotations

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
from .journal_legs import Leg
from .periods import current_period_key


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


# Which side of an entry a plan line's own account sits on. This is just the
# bookkeeping convention: an expense line's account is debited, an income
# line's account is credited, and the counterparty leg is whatever funded or
# received it.
LINE_SIDE: dict[str, str] = {
    "income": "credit",
    "expense": "debit",
    "allocation": "debit",
    "debt_payment": "debit",
    "borrowing": "credit",
    "drawdown": "credit",
}

# Used only when a plan line names no account and has to be matched by text:
# the leg still has to be on a plausible account for that line type.
_LINE_ACCOUNT_TYPES: dict[str, set[str]] = {
    "income": {"income"},
    "expense": {"expense"},
    "allocation": {"asset", "item"},
    "debt_payment": {"liability"},
    "borrowing": {"liability"},
    "drawdown": {"asset", "item"},
}


def _leg_amount(leg: Leg, side: str) -> float:
    return leg.debit if side == "debit" else leg.credit


def _on_side(leg: Leg, side: str) -> bool:
    return _leg_amount(leg, side) > 0


def _matching_legs(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
    *,
    account_id: int | None,
    source_account_id: int | None = None,
    exclude_card_funded: bool = False,
) -> list[Leg]:
    """The legs in `period` that belong to this plan line.

    A plan line claims one side of an entry: the leg on its own account. The
    other legs of the same transaction belong to whatever funded it, and to any
    other plan line that happens to share the payment -- a card bill split
    between an expense account and a receivable matches the expense line with
    its expense leg only, and the receivable leg matches no plan line at all.
    """
    line_type = _line_attr(line, "line_type")
    side = LINE_SIDE.get(line_type)
    if side is None:
        return []
    other = "credit" if side == "debit" else "debit"

    name = (_line_attr(line, "name") or "").strip().lower()
    legs = ctx.period_legs(period)
    by_transaction: dict[int, list[Leg]] = {}
    for leg in legs:
        by_transaction.setdefault(leg.transaction.id, []).append(leg)

    def counterparties(leg: Leg) -> list[Leg]:
        return [
            sibling
            for sibling in by_transaction.get(leg.transaction.id, ())
            if sibling.entry.id != leg.entry.id and _on_side(sibling, other)
        ]

    matched: list[Leg] = []
    for leg in legs:
        if not _on_side(leg, side):
            continue

        if account_id:
            if leg.account.id != account_id:
                continue
        else:
            if leg.account_type not in _LINE_ACCOUNT_TYPES.get(line_type, set()):
                continue
            if not name or name not in (leg.transaction.description or "").lower():
                continue

        funding = counterparties(leg)
        if source_account_id and not any(
            # An allocation taken straight out of income -- a payroll deduction
            # into a stock plan, say -- never passes through the account the
            # plan nominated, and it is still that allocation.
            f.account.id == source_account_id or f.account_type == "income"
            for f in funding
        ):
            continue
        if exclude_card_funded and any(f.account.liability_kind == "card" for f in funding):
            # Settled later by budget_credit_settlement, so it is not cash now.
            continue

        matched.append(leg)
    return matched


def actual_for_plan_line(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
) -> float:
    """What has been posted against this plan line, for budget variance.

    A capsule line reports the capsule's balance rather than the month's
    movement, which is what makes this differ from the cash-flow actual.

    The line's own source account narrows the match, exactly as it does for
    the cash-flow actual. Two lines on one expense account -- a subscription
    paid from a bank and another paid by card -- would otherwise each claim
    the whole account's movement and the month would count it twice.
    """
    target_type = _line_attr(line, "target_type")
    target_id = _line_attr(line, "target_id")
    account_id = _line_attr(line, "account_id")

    if target_type == "capsule" and target_id:
        capsule = ctx.capsule(target_id)
        if capsule:
            return ctx.capsule_balance(capsule)
        account_id = ctx.capsule_account_ids.get(target_id)

    side = LINE_SIDE.get(_line_attr(line, "line_type"))
    if side is None:
        return 0.0
    return sum(
        _leg_amount(leg, side)
        for leg in _matching_legs(
            ctx,
            line,
            period,
            account_id=account_id,
            source_account_id=_line_attr(line, "source_account_id"),
        )
    )


def claimed_leg_ids(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
) -> set[int]:
    """The journal entries this plan line claims as its actuals.

    Exposed so that data_health can ask the opposite question -- which legs on
    a budgeted account no line claims -- with the same rule rather than a
    second copy of it.
    """
    target_type = _line_attr(line, "target_type")
    target_id = _line_attr(line, "target_id")
    account_id = _line_attr(line, "account_id")
    if target_type == "capsule" and target_id and not account_id:
        account_id = ctx.capsule_account_ids.get(target_id)
    if LINE_SIDE.get(_line_attr(line, "line_type")) is None:
        return set()
    return {
        leg.entry.id
        for leg in _matching_legs(
            ctx,
            line,
            period,
            account_id=account_id,
            source_account_id=_line_attr(line, "source_account_id"),
        )
    }


def posted_amount_for_plan_line(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
) -> float:
    """Return posted month movement rather than actual_for_plan_line's capsule balance."""
    target_type = _line_attr(line, "target_type")
    target_id = _line_attr(line, "target_id")
    account_id = _line_attr(line, "account_id")
    if target_type == "capsule" and target_id and not account_id:
        account_id = ctx.capsule_account_ids.get(target_id)
    side = LINE_SIDE.get(_line_attr(line, "line_type"))
    if side is None:
        return 0.0
    return sum(
        _leg_amount(leg, side)
        for leg in _matching_legs(
            ctx,
            line,
            period,
            account_id=account_id,
            source_account_id=_cash_flow_line_source_account_id(ctx, line),
        )
    )


def cash_flow_actual_for_plan_line(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine | dict,
    period: str,
) -> float:
    """What has already moved cash for this plan line in the month.

    Narrower than actual_for_plan_line in two ways. A capsule line reports its
    month's movement, not the capsule balance. And a leg funded from a card is
    left out: the budget was consumed, but the cash moves when the card is
    settled.
    """
    if not plan_line_has_cash_impact(ctx, line):
        return 0.0
    side = LINE_SIDE.get(_line_attr(line, "line_type"))
    if side is None:
        return 0.0
    return sum(
        _leg_amount(leg, side)
        for leg in _matching_legs(
            ctx,
            line,
            period,
            account_id=_cash_flow_line_account_id(ctx, line),
            source_account_id=_cash_flow_line_source_account_id(ctx, line),
            exclude_card_funded=True,
        )
    )


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
