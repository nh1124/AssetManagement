"""The registry side of a month: what the source of truth says should happen.

The registry is the source of truth for recurring cash flow, so these lines
are derived, never stored. Products and recurring transactions that have no
registry entry yet are projected as virtual entries so they still show up in
a plan, and lines that describe the same movement are aggregated into one.
"""
from __future__ import annotations

from types import SimpleNamespace

from .. import models
from .budget_context import BudgetContext
from .budget_lines import _plan_match_key
from .periods import period_to_range
from .registry_service import (
    product_budget_active,
    product_line_type,
    product_unit_amount,
    account_entry_type,
    account_line_type,
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
    line_type = entry.line_type or "expense"
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
            "entry_type": entry.entry_type,
        }],
        "recurring_transaction_ids": [entry.source_recurring_transaction_id]
        if entry.source_recurring_transaction_id else [],
        "product_expense_amount": round(amount, 0) if entry.source_product_id else 0.0,
        "product_expense_items": [{
            "id": entry.source_product_id,
            "name": entry.name,
            "amount": round(amount, 0),
        }] if entry.source_product_id else [],
        "source": "registry",
        "source_kind": "registry",
        "source_id": entry.id,
        "identity_key": "",
        "manual_override": False,
        "cash_treatment": "auto",
        "recurring_transaction_id": entry.source_recurring_transaction_id,
        "sync_status": "missing",
        "is_active": True,
    }


def _virtual_registry_entries(ctx: BudgetContext) -> list[SimpleNamespace]:
    linked_rows = ctx.db.query(
        models.RegistryEntry.source_product_id,
        models.RegistryEntry.source_recurring_transaction_id,
    ).filter(models.RegistryEntry.client_id == ctx.client_id).all()
    existing_product_ids = {product_id for product_id, _ in linked_rows if product_id}
    existing_recurring_ids = {recurring_id for _, recurring_id in linked_rows if recurring_id}
    entries: list[SimpleNamespace] = []

    products = ctx.db.query(models.Product).filter(models.Product.client_id == ctx.client_id).all()
    for product in products:
        if product.id in existing_product_ids or not product_budget_active(product):
            continue
        entries.append(SimpleNamespace(
            id=-product.id,
            client_id=ctx.client_id,
            name=product.name,
            entry_type="asset" if product.is_asset else "item",
            amount=product_unit_amount(product),
            currency="JPY",
            frequency="EveryNDays" if product.frequency_days and product.frequency_days > 0 else "Irregular",
            frequency_days=product.frequency_days or None,
            day_of_month=None,
            month_of_year=None,
            transaction_type="Expense",
            line_type=product_line_type(product),
            budget_account_id=product.budget_account_id,
            source_account_id=None,
            destination_account_id=None,
            source_recurring_transaction_id=None,
            source_product_id=product.id,
            is_active=True,
            budget_active=True,
            start_period=None,
            end_period=None,
        ))

    recurring_rows = ctx.db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == ctx.client_id,
        models.RecurringTransaction.is_active.is_(True),
    ).all()
    for recurring in recurring_rows:
        if recurring.id in existing_recurring_ids or recurring.source_registry_entry_id:
            continue
        line_type = account_line_type(recurring.from_account, recurring.to_account)
        entries.append(SimpleNamespace(
            id=-(1000000 + recurring.id),
            client_id=ctx.client_id,
            name=recurring.name,
            entry_type=account_entry_type(recurring.from_account, recurring.to_account),
            amount=recurring.amount or 0.0,
            currency=recurring.currency or "JPY",
            frequency=recurring.frequency or "Monthly",
            frequency_days=None,
            day_of_month=recurring.day_of_month or 1,
            month_of_year=recurring.month_of_year,
            transaction_type=recurring.type or "Expense",
            line_type=line_type,
            budget_account_id=recurring.to_account_id if line_type in {"expense", "debt_payment"} else None,
            source_account_id=recurring.from_account_id,
            destination_account_id=recurring.to_account_id,
            source_recurring_transaction_id=recurring.id,
            source_product_id=None,
            is_active=True,
            budget_active=True,
            start_period=recurring.start_period,
            end_period=recurring.end_period,
        ))
    return entries


def registry_plan_lines(ctx: BudgetContext, period: str) -> list[dict]:
    return ctx.registry_lines(period, lambda: _build_registry_plan_lines(ctx, period))


def _build_registry_plan_lines(ctx: BudgetContext, period: str) -> list[dict]:
    entries = ctx.db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == ctx.client_id,
        models.RegistryEntry.is_active.is_(True),
        models.RegistryEntry.budget_active.is_(True),
    ).all()
    entries = [*entries, *_virtual_registry_entries(ctx)]
    lines = [line for entry in entries if (line := _registry_plan_line(ctx, entry, period)) is not None]
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
        existing["recurring_transaction_ids"] = [
            *existing.get("recurring_transaction_ids", []),
            *line.get("recurring_transaction_ids", []),
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
        existing["recurring_transaction_id"] = existing.get("recurring_transaction_id") or line.get("recurring_transaction_id")
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
            line["recurring_transaction_ids"] = registry_line.get("recurring_transaction_ids", [])
            if not line.get("source_account_id") and registry_line.get("source_account_id"):
                line["source_account_id"] = registry_line.get("source_account_id")
            line["product_expense_amount"] = registry_line.get("product_expense_amount", 0.0)
            line["product_expense_items"] = registry_line.get("product_expense_items", [])
            line["recurring_amount"] = registry_amount
            line["suggested_amount"] = registry_amount
            line["suggested_source"] = "registry"
            line["recurring_transaction_id"] = line.get("recurring_transaction_id") or registry_line.get("recurring_transaction_id")
            line["sync_status"] = (
                "synced"
                if line.get("source") == "registry" and round(line.get("amount") or 0.0, 0) == registry_amount
                else "diff"
            )
        else:
            line["registry_amount"] = 0.0
            line["recurring_transaction_ids"] = []
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
