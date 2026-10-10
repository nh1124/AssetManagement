"""The monthly budget summary: one response assembled from every planning source.

get_budget_summary is the only consumer that needs all of it at once -- the
Strategy page reads 29 of the 30 keys it returns -- so the assembly lives here
and the sources it draws on live in the budget_* modules beside this one:
plan lines from the store, registry suggestions, credit settlements, actuals,
and the two projections.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from .budget_actuals import actual_for_plan_line
from .budget_context import BudgetContext
from .budget_credit_settlement import _merge_credit_settlement_lines, credit_settlement_plan_lines
from .budget_lines import (
    INFLOW_LINE_TYPES,
    _line_display_name,
    _line_source_id,
    _line_source_kind,
    _sum_actual,
    _sum_lines,
    plan_line_identity_key,
)
from .budget_plan_store import _deduplicate_active_plan_models, resolve_budget_plan_id
from .budget_projection import (
    _balance_projection,
    _cash_flow_projection,
    liquid_cash,
    summarize_balance_projection,
    summarize_cash_flow_projection,
)
from .budget_registry_lines import _merge_registry_lines, registry_plan_lines, registry_totals
from .product_reserve_service import effective_budget_treatment, product_reserve_values


def _serialize_plan_line(
    ctx: BudgetContext,
    line: models.MonthlyPlanLine,
) -> dict:
    name_maps = ctx.target_name_maps
    actual = actual_for_plan_line(ctx, line, line.target_period)
    target_name = _line_display_name(line, name_maps)
    return {
        "id": line.id,
        "target_period": line.target_period,
        "line_type": line.line_type,
        "target_type": line.target_type,
        "target_id": line.target_id,
        "account_id": line.account_id,
        "source_account_id": line.source_account_id,
        "name": line.name,
        "target_name": target_name,
        "account_name": name_maps["account"].get(line.account_id) if line.account_id else None,
        "amount": round(line.amount or 0.0, 0),
        "actual": round(actual, 0),
        "variance": round((line.amount or 0.0) - actual, 0),
        "recurring_amount": 0.0,
        "suggested_amount": 0.0,
        "suggested_source": None,
        "suggested_items": [],
        "suggested_status": None,
        "is_active": line.is_active,
        "source": line.source or "manual",
        "source_kind": _line_source_kind(line),
        "source_id": _line_source_id(line),
        "identity_key": line.identity_key or plan_line_identity_key(line),
        "manual_override": bool(line.manual_override),
        "cash_treatment": line.cash_treatment or "auto",
        "recurring_transaction_id": line.recurring_transaction_id,
        "sync_status": None,
    }


def _virtual_capsule_line(
    ctx: BudgetContext,
    capsule: models.Capsule,
    period: str,
) -> dict:
    line = {
        "id": None,
        "target_period": period,
        "line_type": "allocation",
        "target_type": "capsule",
        "target_id": capsule.id,
        "account_id": capsule.account_id,
        "source_account_id": None,
        "name": capsule.name,
        "target_name": capsule.name,
        "account_name": capsule.account.name if capsule.account else None,
        "amount": round(capsule.monthly_contribution or 0.0, 0),
        "recurring_amount": 0.0,
        "suggested_amount": round(capsule.monthly_contribution or 0.0, 0)
        if capsule.capsule_type == "product_pool" else 0.0,
        "suggested_source": "product_reserve" if capsule.capsule_type == "product_pool" else None,
        "suggested_items": product_reserve_source_items(ctx.db, capsule) if capsule.capsule_type == "product_pool" else [],
        "suggested_status": "synced" if capsule.capsule_type == "product_pool" else None,
        "is_active": True,
        "source": "capsule",
        "source_kind": "capsule",
        "source_id": capsule.id,
        "identity_key": "",
        "manual_override": False,
        "cash_treatment": "cash",
        "recurring_transaction_id": None,
        "sync_status": None,
    }
    actual = actual_for_plan_line(ctx, line, period)
    line["actual"] = round(actual, 0)
    line["variance"] = round((capsule.monthly_contribution or 0.0) - actual, 0)
    return line


def product_reserve_source_items(db: Session, capsule: models.Capsule) -> list[dict]:
    products = db.query(models.Product).filter(
        models.Product.client_id == capsule.client_id,
        models.Product.funding_capsule_id == capsule.id,
    ).order_by(models.Product.name).all()
    items = []
    for product in products:
        if effective_budget_treatment(product) not in {"reserve_allocation", "asset_replacement"}:
            continue
        values = product_reserve_values(product)
        items.append({
            "id": product.id,
            "name": product.name,
            "amount": values["recommended_monthly_reserve"],
            "source": "product_reserve",
        })
    return items


def _attach_capsule_suggestions(ctx: BudgetContext, plan_lines: list[dict]) -> None:
    for line in plan_lines:
        if line.get("line_type") != "allocation" or line.get("target_type") != "capsule":
            continue
        capsule = ctx.capsule(line.get("target_id"))
        if not capsule or capsule.capsule_type != "product_pool":
            continue
        suggested = round(capsule.monthly_contribution or 0.0, 0)
        line["suggested_amount"] = suggested
        line["suggested_source"] = "product_reserve"
        line["suggested_items"] = product_reserve_source_items(ctx.db, capsule)
        line["suggested_status"] = (
            "synced"
            if line.get("source") == "capsule" and round(line.get("amount") or 0.0, 0) == suggested
            else "diff"
        )


def get_budget_summary(
    db: Session,
    client_id: int,
    period: str,
    plan_id: int | None = None,
    cash_flow_start_period: str | None = None,
    cash_flow_months: int = 12,
    goal_metrics: dict | None = None,
) -> dict:
    """Build the monthly cash-flow plan summary.

    goal_metrics carries the goal-derived advisory figures (goals_count /
    total_goal_gap / required_monthly_savings). The caller supplies them --
    see strategy_service.summarize_goal_funding_gap -- so that planning never
    depends on the goal domain.
    """
    ctx = BudgetContext(db, client_id)
    plan_id = resolve_budget_plan_id(db, client_id, plan_id)

    goal_metrics = goal_metrics or {}
    goals_count = int(goal_metrics.get("goals_count") or 0)
    total_gap = float(goal_metrics.get("total_goal_gap") or 0.0)
    required_monthly_savings = float(goal_metrics.get("required_monthly_savings") or 0.0)

    recurring = registry_totals(ctx, period)
    capsule_by_life_event_id = ctx.capsule_by_life_event_id

    plan_models = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.target_period == period,
        models.MonthlyPlanLine.is_active.is_(True),
        models.MonthlyPlanLine.plan_id == plan_id,
    ).order_by(models.MonthlyPlanLine.line_type, models.MonthlyPlanLine.id).all()
    plan_models = _deduplicate_active_plan_models(db, plan_models)
    plan_lines = [_serialize_plan_line(ctx, line) for line in plan_models]
    for line in plan_lines:
        if line.get("line_type") == "allocation" and line.get("target_type") == "life_event":
            capsule = capsule_by_life_event_id.get(line.get("target_id"))
            if capsule:
                line["target_type"] = "capsule"
                line["target_id"] = capsule.id
                line["account_id"] = capsule.account_id
                line["name"] = capsule.name
                line["target_name"] = capsule.name
                line["account_name"] = capsule.account.name if capsule.account else None
                actual = actual_for_plan_line(ctx, line, period)
                line["actual"] = round(actual, 0)
                line["variance"] = round((line.get("amount") or 0.0) - actual, 0)

    _attach_capsule_suggestions(ctx, plan_lines)
    existing_capsule_ids = {
        line.get("target_id")
        for line in plan_lines
        if line.get("line_type") == "allocation" and line.get("target_type") == "capsule"
    }
    for capsule in ctx.capsules:
        if capsule.id not in existing_capsule_ids:
            plan_lines.append(_virtual_capsule_line(ctx, capsule, period))
    plan_lines = _merge_registry_lines(plan_lines, registry_plan_lines(ctx, period))
    plan_lines = _merge_credit_settlement_lines(plan_lines, credit_settlement_plan_lines(ctx, period, plan_id))

    expense_lines = [line for line in plan_lines if line["line_type"] == "expense"]
    allocation_lines = [line for line in plan_lines if line["line_type"] == "allocation"]
    debt_lines = [line for line in plan_lines if line["line_type"] == "debt_payment"]
    inflow_lines = [line for line in plan_lines if line["line_type"] in INFLOW_LINE_TYPES]
    capsule_lines = [line for line in allocation_lines if line.get("target_type") == "capsule"]

    monthly_income = recurring["income"]
    total_income_plan = _sum_lines(inflow_lines, "income")
    total_borrowing_plan = _sum_lines(inflow_lines, "borrowing")
    total_drawdown_plan = _sum_lines(inflow_lines, "drawdown")
    total_expected_inflow = total_income_plan + total_borrowing_plan + total_drawdown_plan

    total_variable_budget = _sum_lines(expense_lines, "expense")
    total_allocation_plan = _sum_lines(allocation_lines, "allocation")
    total_debt_plan = _sum_lines(debt_lines, "debt_payment")
    total_capsule_plan = _sum_lines(capsule_lines, "allocation")
    total_capsule_actual = _sum_actual(capsule_lines, "allocation")

    remaining = (
        total_expected_inflow
        - total_variable_budget
        - total_allocation_plan
        - total_debt_plan
    )
    starting_cash = liquid_cash(ctx)
    ending_cash_after_plan = starting_cash + remaining
    feasibility_status = "ok"
    if remaining < 0:
        feasibility_status = "warning"
    if ending_cash_after_plan < 0:
        feasibility_status = "shortfall"

    projection_start = cash_flow_start_period or period
    projection = _cash_flow_projection(ctx, projection_start, months=cash_flow_months, starting_cash=starting_cash, plan_id=plan_id)
    cash_flow_summary = summarize_cash_flow_projection(projection, starting_cash, projection_start)
    balance_projection = _balance_projection(ctx, projection_start, months=cash_flow_months, plan_id=plan_id)
    balance_summary = summarize_balance_projection(balance_projection)

    return {
        "period": period,
        "plan_id": plan_id,
        "required_monthly_savings": round(required_monthly_savings, 0),
        "monthly_fixed_costs": round(recurring["fixed_costs"], 0),
        "monthly_income": round(monthly_income, 0),
        "recurring_debt_payments": round(recurring["debt_payments"], 0),
        "recurring_allocations": round(recurring["allocations"], 0),
        "recurring_borrowing": round(recurring["borrowing"], 0),
        "total_income_plan": round(total_income_plan, 0),
        "total_expected_inflow": round(total_expected_inflow, 0),
        "total_variable_budget": round(total_variable_budget, 0),
        "total_allocation_plan": round(total_allocation_plan, 0),
        "total_debt_plan": round(total_debt_plan, 0),
        "total_capsule_plan": round(total_capsule_plan, 0),
        "total_capsule_actual": round(total_capsule_actual, 0),
        "remaining_balance": round(remaining, 0),
        "starting_cash": round(starting_cash, 0),
        "ending_cash_after_plan": round(ending_cash_after_plan, 0),
        "feasibility_status": feasibility_status,
        "plan_lines": plan_lines,
        "expense_accounts": [
            {
                "id": line.get("id")
                or (
                    -(line.get("registry_entry_ids") or [0])[0]
                    if line.get("registry_entry_ids")
                    else line.get("account_id") or -(line.get("recurring_transaction_id") or 0)
                ),
                "account_id": line["account_id"],
                "source_account_id": line.get("source_account_id"),
                "target_type": line.get("target_type"),
                "target_id": line.get("target_id"),
                "name": line["target_name"],
                "amount": line["amount"],
                "balance": line["actual"],
                "plan_line_id": line.get("id"),
                "recurring_amount": line.get("recurring_amount", 0.0),
                "registry_amount": line.get("registry_amount", 0.0),
                "registry_entry_ids": line.get("registry_entry_ids", []),
                "registry_items": line.get("registry_items", []),
                "recurring_transaction_ids": line.get("recurring_transaction_ids", []),
                "product_expense_amount": line.get("product_expense_amount", 0.0),
                "product_expense_items": line.get("product_expense_items", []),
                "suggested_amount": line.get("suggested_amount", 0.0),
                "suggested_source": line.get("suggested_source"),
                "suggested_status": line.get("suggested_status"),
                "source": line.get("source"),
                "source_kind": line.get("source_kind"),
                "source_id": line.get("source_id"),
                "manual_override": line.get("manual_override", False),
                "cash_treatment": line.get("cash_treatment", "auto"),
                "sync_status": line.get("sync_status"),
                "recurring_transaction_id": line.get("recurring_transaction_id"),
            }
            for line in expense_lines
        ],
        "others_actual": 0,
        "sinking_funds": [
            {
                "id": line["target_id"] or line["id"] or 0,
                "name": line["target_name"],
                "life_event_id": None,
                "account_id": line["account_id"],
                "planned": line["amount"],
                "actual": line["actual"],
                "variance": line["variance"],
                "current_balance": round(
                    ctx.capsule_balance(capsule)
                    if (capsule := ctx.capsule(line.get("target_id")))
                    else 0.0,
                    0,
                ),
                "target_amount": round(
                    capsule.target_amount if (capsule := ctx.capsule(line.get("target_id"))) else 0.0,
                    0,
                ),
            }
            for line in capsule_lines
        ],
        "cash_flow_projection": projection,
        "cash_flow_summary": cash_flow_summary,
        "balance_projection": balance_projection,
        "balance_summary": balance_summary,
        "goals_count": goals_count,
        "total_goal_gap": round(total_gap, 0),
    }
