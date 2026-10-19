"""Automatic schedules and product proposals, aggregated by the saved budget identity."""
from __future__ import annotations

from .. import models
from .budget_context import BudgetContext
from .budget_lines import _plan_match_key
from .fx_service import get_client_currency
from .periods import period_to_range
from .registry_service import (
    product_budget_active,
    product_line_type,
    product_unit_amount,
    LINE_TYPES,
    registry_entry_amount_for_period,
    registry_source_account_id,
    registry_target_account_id,
)


def _registry_plan_line(
    ctx: BudgetContext,
    entry: models.RegistryEntry,
    period: str,
) -> dict | None:
    name_maps = ctx.target_name_maps
    period_start, _ = period_to_range(period)
    amount = registry_entry_amount_for_period(ctx.db, entry, period, period_start, entry.client_id)
    if amount <= 0:
        return None
    line_type = LINE_TYPES[entry.kind]
    account_id = registry_target_account_id(entry)
    source_account_id = registry_source_account_id(entry)
    target_type = "account" if account_id else "manual"
    target_name = name_maps["account"].get(account_id, entry.name) if account_id else entry.name
    return {
        "id": None,
        "target_period": period,
        "line_type": line_type,
        "target_type": target_type,
        "target_id": None,
        "account_id": account_id,
        "source_account_id": source_account_id,
        "name": entry.name,
        "target_name": target_name,
        "account_name": name_maps["account"].get(account_id) if account_id else None,
        "amount": 0.0,
        "actual": 0.0,
        "variance": 0.0,
        "recurring_amount": round(amount, 0),
        "suggested_amount": round(amount, 0),
        "suggested_source": "registry",
        "suggested_status": "missing",
        "registry_amount": round(amount, 0),
        "registry_entry_id": entry.id,
        "registry_entry_ids": [entry.id],
        "registry_items": [{
            "id": entry.id,
            "name": entry.name,
            "amount": round(amount, 0),
            "source": "registry",
            "kind": entry.kind,
        }],
        "product_expense_amount": 0.0,
        "product_expense_items": [],
        "source": "registry",
        "source_kind": "registry",
        "identity_key": "",
        "manual_override": False,
        "cash_treatment": "auto",
        "sync_status": "missing",
        "is_active": True,
    }


def _product_plan_lines(ctx: BudgetContext, period: str) -> list[dict]:
    # Products propose a monthly consumption cost; they never create automatic transactions.
    from .fx_service import convert_amount
    period_start, _ = period_to_range(period)
    lines = []
    for product in ctx.db.query(models.Product).filter(models.Product.client_id == ctx.client_id).all():
        if not product_budget_active(product) or not product.frequency_days or product.frequency_days <= 0:
            continue
        amount = convert_amount(ctx.db, ctx.client_id, product_unit_amount(product) * 30 / product.frequency_days,
                                get_client_currency(ctx.db, ctx.client_id), as_of_date=period_start)
        account_id = product.budget_account_id
        name = ctx.target_name_maps["account"].get(account_id, product.name)
        lines.append({"id": None, "target_period": period, "line_type": product_line_type(product),
                      "target_type": "account", "target_id": None, "account_id": account_id, "source_account_id": None,
                      "name": name, "target_name": name, "account_name": name, "amount": 0, "actual": 0, "variance": 0,
                      "recurring_amount": amount, "suggested_amount": amount, "registry_amount": amount,
                      "suggested_source": "registry", "suggested_status": "missing", "registry_entry_ids": [], "registry_items": [],
                      "product_expense_amount": amount, "product_expense_items": [{"id": product.id, "name": product.name, "amount": amount}],
                      "source": "registry", "source_kind": "registry", "identity_key": "", "manual_override": False,
                      "cash_treatment": "auto", "sync_status": "missing", "is_active": True})
    return lines


def registry_plan_lines(ctx: BudgetContext, period: str) -> list[dict]:
    return ctx.registry_lines(period, lambda: _build_registry_plan_lines(ctx, period))


def _build_registry_plan_lines(ctx: BudgetContext, period: str) -> list[dict]:
    entries = ctx.db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == ctx.client_id,
        models.RegistryEntry.is_active.is_(True),
        models.RegistryEntry.budget_active.is_(True),
    ).all()
    lines = [line for entry in entries if (line := _registry_plan_line(ctx, entry, period)) is not None]
    lines.extend(_product_plan_lines(ctx, period))
    aggregated: dict[tuple, dict] = {}
    for line in lines:
        key = _plan_match_key(
            line["line_type"],
            line["target_type"],
            line["account_id"],
            line["name"],
            line.get("source_account_id"),
            line.get("cash_treatment"),
        )
        if key not in aggregated:
            item = dict(line)
            if item["account_id"]:
                item["name"] = item["account_name"] or item["target_name"]
                item["target_name"] = item["account_name"] or item["target_name"]
            aggregated[key] = item
            continue
        existing = aggregated[key]
        existing["recurring_amount"] = round((existing.get("recurring_amount") or 0.0) + (line.get("recurring_amount") or 0.0), 0)
        existing["suggested_amount"] = round((existing.get("suggested_amount") or 0.0) + (line.get("suggested_amount") or 0.0), 0)
        existing["registry_amount"] = round((existing.get("registry_amount") or 0.0) + (line.get("registry_amount") or 0.0), 0)
        existing["registry_entry_ids"] = [
            *existing.get("registry_entry_ids", []),
            *line.get("registry_entry_ids", []),
        ]
        existing["registry_items"] = [
            *existing.get("registry_items", []),
            *line.get("registry_items", []),
        ]
        existing["product_expense_amount"] = round(
            (existing.get("product_expense_amount") or 0.0)
            + (line.get("product_expense_amount") or 0.0),
            0,
        )
        existing["product_expense_items"] = [
            *existing.get("product_expense_items", []),
            *line.get("product_expense_items", []),
        ]
    return list(aggregated.values())


def registry_totals(ctx: BudgetContext, period: str) -> dict[str, float]:
    totals = {
        "income": 0.0,
        "fixed_costs": 0.0,
        "debt_payments": 0.0,
        "allocations": 0.0,
        "borrowing": 0.0,
    }
    for line in registry_plan_lines(ctx, period):
        amount = line.get("registry_amount") or line.get("suggested_amount") or 0.0
        line_type = line.get("line_type")
        if line_type == "income":
            totals["income"] += amount
        elif line_type == "expense":
            totals["fixed_costs"] += amount
        elif line_type == "debt_payment":
            totals["debt_payments"] += amount
        elif line_type == "allocation":
            totals["allocations"] += amount
        elif line_type == "borrowing":
            totals["borrowing"] += amount
    return totals


def _merge_registry_lines(plan_lines: list[dict], registry_lines: list[dict]) -> list[dict]:
    registry_by_key = {
        _plan_match_key(
            line["line_type"],
            line["target_type"],
            line["account_id"],
            line["name"],
            line.get("source_account_id"),
            line.get("cash_treatment"),
        ): line
        for line in registry_lines
    }
    registry_by_key_without_source = {
        _plan_match_key(
            line["line_type"],
            line["target_type"],
            line["account_id"],
            line["name"],
            None,
            line.get("cash_treatment"),
        ): line
        for line in registry_lines
    }
    # Secondary index: (line_type, entry_name, source_account_id, cash_treatment) for fallback when account_id differs between
    # an existing DB plan line (account_id=None) and the registry line (account_id set).
    registry_by_entry_name: dict[tuple, dict] = {}
    for reg_line in registry_lines:
        lt = reg_line.get("line_type") or ""
        cash_treatment = reg_line.get("cash_treatment") or "auto"
        source_account_id = reg_line.get("source_account_id") or 0
        for item in reg_line.get("registry_items", []):
            entry_name = (item.get("name") or "").strip().lower()
            if entry_name:
                registry_by_entry_name.setdefault((lt, entry_name, source_account_id, cash_treatment), reg_line)

    matched_keys: set[tuple] = set()
    for line in plan_lines:
        primary_key = _plan_match_key(
            line.get("line_type"),
            line.get("target_type"),
            line.get("account_id"),
            line.get("name") or line.get("target_name"),
            line.get("source_account_id"),
            line.get("cash_treatment"),
        )
        registry_line = registry_by_key.get(primary_key)
        if not registry_line and not line.get("source_account_id"):
            registry_line = registry_by_key_without_source.get(_plan_match_key(
                line.get("line_type"),
                line.get("target_type"),
                line.get("account_id"),
                line.get("name") or line.get("target_name"),
                None,
                line.get("cash_treatment"),
            ))
        if not registry_line:
            plan_name = (line.get("name") or line.get("target_name") or "").strip().lower()
            if plan_name:
                registry_line = registry_by_entry_name.get((
                    line.get("line_type") or "",
                    plan_name,
                    line.get("source_account_id") or 0,
                    line.get("cash_treatment") or "auto",
                ))
        registry_amount = round((registry_line or {}).get("registry_amount") or 0.0, 0)
        if registry_line:
            matched_keys.add(_plan_match_key(
                registry_line["line_type"],
                registry_line["target_type"],
                registry_line["account_id"],
                registry_line["name"],
                registry_line.get("source_account_id"),
                registry_line.get("cash_treatment"),
            ))
            line["registry_amount"] = registry_amount
            line["registry_entry_ids"] = registry_line.get("registry_entry_ids", [])
            line["registry_items"] = registry_line.get("registry_items", [])
            if not line.get("source_account_id") and registry_line.get("source_account_id"):
                line["source_account_id"] = registry_line.get("source_account_id")
            line["product_expense_amount"] = registry_line.get("product_expense_amount", 0.0)
            line["product_expense_items"] = registry_line.get("product_expense_items", [])
            line["recurring_amount"] = registry_amount
            line["suggested_amount"] = registry_amount
            line["suggested_source"] = "registry"
            line["sync_status"] = (
                "synced"
                if line.get("source") == "registry" and round(line.get("amount") or 0.0, 0) == registry_amount
                else "diff"
            )
        else:
            line["registry_amount"] = 0.0
            line["product_expense_amount"] = 0.0
            line["product_expense_items"] = []
            if line.get("suggested_source") is None:
                line["sync_status"] = None

    plan_lines.extend([
        line for line in registry_lines
        if _plan_match_key(
            line["line_type"],
            line["target_type"],
            line["account_id"],
            line["name"],
            line.get("source_account_id"),
            line.get("cash_treatment"),
        ) not in matched_keys
    ])
    return plan_lines
