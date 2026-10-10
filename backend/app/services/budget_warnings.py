"""Where the saved plan disagrees with what the upstream sources imply.

A warning is always a comparison against something generated: a registry
line, a product-pool capsule's monthly reserve, or a credit settlement. Each
one is either missing from the plan entirely or present with a different
amount, and the cash-flow projection surfaces them per month.
"""
from __future__ import annotations

from .. import models
from .budget_context import BudgetContext
from .budget_credit_settlement import credit_settlement_plan_lines
from .budget_lines import _plan_match_key
from .budget_registry_lines import registry_plan_lines


def budget_setup_warnings(
    ctx: BudgetContext,
    period: str,
    plan_models: list[models.MonthlyPlanLine],
    plan_id: int | None = None,
) -> list[dict]:
    return [
        *recurrence_setup_warnings(ctx, period, plan_models),
        *credit_settlement_setup_warnings(ctx, period, plan_models, plan_id),
        *product_reserve_setup_warnings(ctx, plan_models),
    ]


def recurrence_setup_warnings(
    ctx: BudgetContext,
    period: str,
    plan_models: list[models.MonthlyPlanLine],
) -> list[dict]:
    registry_lines = registry_plan_lines(ctx, period)
    plan_by_key = {
        _plan_match_key(
            line.line_type,
            line.target_type,
            line.account_id,
            line.name,
            line.source_account_id,
            line.cash_treatment,
        ): line
        for line in plan_models
    }
    warnings = []
    for registry_line in registry_lines:
        matched = plan_by_key.get(_plan_match_key(
            registry_line["line_type"],
            registry_line["target_type"],
            registry_line["account_id"],
            registry_line["name"],
            registry_line.get("source_account_id"),
            registry_line.get("cash_treatment"),
        ))
        if not matched:
            warnings.append({
                "type": "missing_budget",
                "recurring_transaction_id": registry_line.get("recurring_transaction_id"),
                "registry_entry_ids": registry_line.get("registry_entry_ids", []),
                "source": "registry",
                "name": registry_line["name"],
                "amount": registry_line["registry_amount"],
            })
            continue
        if round(matched.amount or 0.0, 0) != round(registry_line["registry_amount"], 0):
            warnings.append({
                "type": "amount_diff",
                "recurring_transaction_id": registry_line.get("recurring_transaction_id"),
                "registry_entry_ids": registry_line.get("registry_entry_ids", []),
                "source": "registry",
                "name": registry_line["name"],
                "amount": registry_line["registry_amount"],
                "budget_amount": round(matched.amount or 0.0, 0),
            })
    return warnings


def product_reserve_setup_warnings(
    ctx: BudgetContext,
    plan_models: list[models.MonthlyPlanLine],
) -> list[dict]:
    capsules = ctx.db.query(models.Capsule).filter(
        models.Capsule.client_id == ctx.client_id,
        models.Capsule.capsule_type == "product_pool",
        models.Capsule.monthly_contribution > 0,
    ).all()
    plan_by_capsule_id = {
        line.target_id: line
        for line in plan_models
        if line.line_type == "allocation"
        and line.target_type == "capsule"
        and line.target_id is not None
    }
    warnings = []
    for capsule in capsules:
        expected = round(capsule.monthly_contribution or 0.0, 0)
        matched = plan_by_capsule_id.get(capsule.id)
        if not matched:
            warnings.append({
                "type": "missing_product_reserve",
                "source": "product_reserve",
                "capsule_id": capsule.id,
                "account_id": capsule.account_id,
                "name": capsule.name,
                "amount": expected,
            })
            continue
        budget_amount = round(matched.amount or 0.0, 0)
        if budget_amount != expected:
            warnings.append({
                "type": "product_reserve_diff",
                "source": "product_reserve",
                "capsule_id": capsule.id,
                "account_id": capsule.account_id,
                "plan_line_id": matched.id,
                "name": capsule.name,
                "amount": expected,
                "budget_amount": budget_amount,
            })
    return warnings


def credit_settlement_setup_warnings(
    ctx: BudgetContext,
    period: str,
    plan_models: list[models.MonthlyPlanLine],
    plan_id: int | None = None,
) -> list[dict]:
    plan_by_account = {
        line.account_id: line
        for line in plan_models
        if line.line_type == "debt_payment" and line.account_id is not None
    }
    warnings = []
    for settlement in credit_settlement_plan_lines(ctx, period, plan_id):
        amount = round(settlement.get("suggested_amount") or 0.0, 0)
        matched = plan_by_account.get(settlement.get("account_id"))
        if not matched:
            warnings.append({
                "type": "missing_credit_settlement",
                "source": "credit_settlement",
                "account_id": settlement.get("account_id"),
                "name": settlement.get("target_name") or settlement.get("name"),
                "amount": amount,
            })
            continue
        budget_amount = round(matched.amount or 0.0, 0)
        if budget_amount != amount:
            warnings.append({
                "type": "credit_settlement_diff",
                "source": "credit_settlement",
                "account_id": settlement.get("account_id"),
                "plan_line_id": matched.id,
                "name": settlement.get("target_name") or settlement.get("name"),
                "amount": amount,
                "budget_amount": budget_amount,
            })
    return warnings
