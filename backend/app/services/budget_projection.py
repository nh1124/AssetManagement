"""Rolling the plan forward: cash on hand and the balance sheet, month by month.

Both projections walk the same months over the same plan lines and differ in
what they accumulate -- one the cash flow of each movement, the other the
asset and liability balances it leaves behind. For the current month they
count the remaining amount rather than the full plan, so actuals already
posted are not charged twice.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from .budget_actuals import (
    _balance_movement_for_amount,
    _projection_amounts_for_period,
    plan_line_flow_for_amount,
)
from .budget_context import BudgetContext
from .budget_lines import (
    ASSET_FLOW_BUCKETS,
    LIQUID_ACCOUNT_NAMES,
    _add_flow,
    _empty_balance,
    _empty_flow,
    account_flow_bucket,
)
from .budget_plan_store import _deduplicate_active_plan_models, resolve_budget_plan_id
from .budget_warnings import budget_setup_warnings
from .fx_service import calculate_account_valued_balance
from .periods import add_months


def liquid_cash(ctx: BudgetContext) -> float:
    """Cash the plan can actually draw on: operating accounts and plain cash."""
    accounts = [
        account
        for account in ctx.accounts.values()
        if account.account_type == "asset"
        and account.is_active
        and ((account.name or "") in LIQUID_ACCOUNT_NAMES or account.role == "operating")
    ]
    return sum(calculate_account_valued_balance(ctx.db, account) for account in accounts)


def _starting_balance_state(ctx: BudgetContext) -> dict[str, float]:
    state = _empty_balance()
    accounts = ctx.db.query(models.Account).filter(
        models.Account.client_id == ctx.client_id,
        models.Account.is_active.is_(True),
    ).all()
    for account in accounts:
        balance = calculate_account_valued_balance(ctx.db, account)
        bucket = account_flow_bucket(account)
        if bucket in ASSET_FLOW_BUCKETS:
            state[bucket] += balance
        elif bucket == "liability":
            state["liabilities"] += balance
    return state


def _balance_projection_row(period: str, state: dict[str, float]) -> dict:
    total_assets = sum(state[bucket] for bucket in ASSET_FLOW_BUCKETS)
    liabilities = state["liabilities"]
    return {
        "period": period,
        "operating_assets": round(state["operating"], 0),
        "defense_assets": round(state["defense"], 0),
        "earmarked_assets": round(state["earmarked"], 0),
        "growth_assets": round(state["growth"], 0),
        "unassigned_assets": round(state["unassigned"], 0),
        "total_assets": round(total_assets, 0),
        "liabilities": round(liabilities, 0),
        "net_worth": round(total_assets - liabilities, 0),
    }


def get_cash_flow_projection(
    db: Session,
    client_id: int,
    start_period: str,
    months: int = 12,
    starting_cash: float | None = None,
    plan_id: int | None = None,
) -> list[dict]:
    return _cash_flow_projection(
        BudgetContext(db, client_id),
        start_period,
        months=months,
        starting_cash=starting_cash,
        plan_id=plan_id,
    )


def _cash_flow_projection(
    ctx: BudgetContext,
    start_period: str,
    *,
    months: int = 12,
    starting_cash: float | None = None,
    plan_id: int | None = None,
) -> list[dict]:
    plan_id = resolve_budget_plan_id(ctx.db, ctx.client_id, plan_id)
    cash = liquid_cash(ctx) if starting_cash is None else starting_cash
    rows = []
    for idx in range(months):
        period = add_months(start_period, idx)
        q = ctx.db.query(models.MonthlyPlanLine).filter(
            models.MonthlyPlanLine.client_id == ctx.client_id,
            models.MonthlyPlanLine.target_period == period,
            models.MonthlyPlanLine.is_active.is_(True),
            models.MonthlyPlanLine.plan_id == plan_id,
        )
        lines = q.all()
        lines = _deduplicate_active_plan_models(ctx.db, lines)
        projection_lines: list[models.MonthlyPlanLine | dict] = list(lines)
        planned_flow = _empty_flow()
        actual_flow = _empty_flow()
        remaining_flow = _empty_flow()
        for line in projection_lines:
            planned_amount, actual_amount, remaining_amount = _projection_amounts_for_period(ctx, line, period)
            _add_flow(planned_flow, plan_line_flow_for_amount(ctx, line, planned_amount))
            _add_flow(actual_flow, plan_line_flow_for_amount(ctx, line, actual_amount))
            _add_flow(remaining_flow, plan_line_flow_for_amount(ctx, line, remaining_amount))
        income = remaining_flow["inflow"]
        expense = remaining_flow["expense"]
        allocation = remaining_flow["allocation"]
        debt = remaining_flow["debt"]
        net = remaining_flow["operating"]
        cash += net
        setup_warnings = budget_setup_warnings(ctx, period, lines)
        rows.append({
            "period": period,
            "inflow": round(income, 0),
            "expense": round(expense, 0),
            "allocation": round(allocation, 0),
            "debt": round(debt, 0),
            "net_cash": round(net, 0),
            "ending_cash": round(cash, 0),
            "planned_inflow": round(planned_flow["inflow"], 0),
            "actual_inflow": round(actual_flow["inflow"], 0),
            "remaining_inflow": round(remaining_flow["inflow"], 0),
            "planned_expense": round(planned_flow["expense"], 0),
            "actual_expense": round(actual_flow["expense"], 0),
            "remaining_expense": round(remaining_flow["expense"], 0),
            "planned_allocation": round(planned_flow["allocation"], 0),
            "actual_allocation": round(actual_flow["allocation"], 0),
            "remaining_allocation": round(remaining_flow["allocation"], 0),
            "planned_debt": round(planned_flow["debt"], 0),
            "actual_debt": round(actual_flow["debt"], 0),
            "remaining_debt": round(remaining_flow["debt"], 0),
            "operating_flow": round(remaining_flow["operating"], 0),
            "defense_flow": round(remaining_flow["defense"], 0),
            "earmarked_flow": round(remaining_flow["earmarked"], 0),
            "growth_flow": round(remaining_flow["growth"], 0),
            "unassigned_asset_flow": round(remaining_flow["unassigned"], 0),
            "financing_flow": round(remaining_flow["financing"], 0),
            "internal_transfer": round(remaining_flow["internal_transfer"], 0),
            "non_cash_budget": round(remaining_flow["non_cash_budget"], 0),
            "status": "shortfall" if cash < 0 else ("warning" if setup_warnings or net < 0 else "ok"),
            "setup_warnings": setup_warnings,
        })
    return rows


def get_balance_projection(
    db: Session,
    client_id: int,
    start_period: str,
    months: int = 12,
    plan_id: int | None = None,
) -> list[dict]:
    return _balance_projection(BudgetContext(db, client_id), start_period, months=months, plan_id=plan_id)


def _balance_projection(
    ctx: BudgetContext,
    start_period: str,
    *,
    months: int = 12,
    plan_id: int | None = None,
) -> list[dict]:
    plan_id = resolve_budget_plan_id(ctx.db, ctx.client_id, plan_id)
    state = _starting_balance_state(ctx)
    rows = []
    for idx in range(months):
        period = add_months(start_period, idx)
        lines = (
            ctx.db.query(models.MonthlyPlanLine)
            .filter(
                models.MonthlyPlanLine.client_id == ctx.client_id,
                models.MonthlyPlanLine.target_period == period,
                models.MonthlyPlanLine.is_active.is_(True),
                models.MonthlyPlanLine.plan_id == plan_id,
            )
            .all()
        )
        lines = _deduplicate_active_plan_models(ctx.db, lines)
        projection_lines: list[models.MonthlyPlanLine | dict] = list(lines)
        for line in projection_lines:
            _, _, remaining_amount = _projection_amounts_for_period(ctx, line, period)
            movement = _balance_movement_for_amount(ctx, line, remaining_amount)
            for key, value in movement.items():
                state[key] = state.get(key, 0.0) + (value or 0.0)
        rows.append(_balance_projection_row(period, state))
    return rows


def summarize_cash_flow_projection(
    projection: list[dict],
    starting_cash: float,
    start_period: str,
) -> dict[str, float | int | str | None]:
    cash_points = [round(starting_cash, 0)] + [row["ending_cash"] for row in projection]
    lowest_cash = min(cash_points) if cash_points else round(starting_cash, 0)
    shortfall_month = start_period if starting_cash < 0 else None
    runway_months = 0 if starting_cash < 0 else len(projection)

    if starting_cash >= 0:
        for index, row in enumerate(projection):
            if row["ending_cash"] < 0:
                shortfall_month = row["period"]
                runway_months = index
                break

    return {
        "runway_months": runway_months,
        "lowest_cash": round(lowest_cash, 0),
        "required_buffer": round(max(0.0, -lowest_cash), 0),
        "shortfall_month": shortfall_month,
        "horizon_months": len(projection),
    }


def summarize_balance_projection(projection: list[dict]) -> dict[str, float | int]:
    if not projection:
        return {
            "horizon_months": 0,
            "ending_total_assets": 0.0,
            "ending_liabilities": 0.0,
            "ending_net_worth": 0.0,
            "lowest_net_worth": 0.0,
        }
    return {
        "horizon_months": len(projection),
        "ending_total_assets": projection[-1]["total_assets"],
        "ending_liabilities": projection[-1]["liabilities"],
        "ending_net_worth": projection[-1]["net_worth"],
        "lowest_net_worth": min(row["net_worth"] for row in projection),
    }
