"""Monthly cash-flow planning and budget summary helpers."""
from __future__ import annotations

from datetime import date, datetime
import json
from types import SimpleNamespace
from typing import Iterable

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import models
from .capsule_service import capsule_balance
from .fx_service import calculate_account_valued_balance, convert_amount, convert_transaction_amount
from .goal_service import get_life_events_with_progress
from .product_reserve_service import effective_budget_treatment, product_reserve_values
from .registry_service import (
    product_budget_active,
    product_line_type,
    product_unit_amount,
    recurring_entry_type,
    recurring_line_type,
    registry_entry_amount_for_period,
    registry_source_account_id,
    registry_target_account_id,
)


LIQUID_ACCOUNT_NAMES = {"cash", "bank", "savings"}
INFLOW_LINE_TYPES = {"income", "borrowing", "drawdown"}
OUTFLOW_LINE_TYPES = {"expense", "allocation", "debt_payment"}
NON_CASH_TRANSACTION_TYPES = {"CreditExpense", "CreditAssetPurchase"}
ASSET_FLOW_BUCKETS = ("operating", "defense", "earmarked", "growth", "unassigned")


BudgetSummaryContext = dict[str, dict]


def _period_transactions_cached(
    db: Session,
    client_id: int,
    period: str,
    context: BudgetSummaryContext | None = None,
) -> list[models.Transaction]:
    if context is None:
        return _period_transactions(db, client_id, period)
    cache = context.setdefault("period_transactions", {})
    if period not in cache:
        cache[period] = _period_transactions(db, client_id, period)
    return cache[period]


def get_or_create_default_plan(db: Session, client_id: int) -> models.BudgetPlan:
    plan = db.query(models.BudgetPlan).filter_by(client_id=client_id, is_default=True).first()
    if not plan:
        plan = models.BudgetPlan(client_id=client_id, name="Baseline", is_default=True, sort_order=0)
        db.add(plan)
        db.commit()
        db.refresh(plan)
    changed = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id.is_(None),
        models.MonthlyPlanLine.is_active.is_(True),
    ).update({"plan_id": plan.id})
    if changed:
        db.commit()
        db.refresh(plan)
    return plan


def resolve_budget_plan_id(db: Session, client_id: int, plan_id: int | None = None) -> int:
    if plan_id is None:
        return get_or_create_default_plan(db, client_id).id
    exists = db.query(models.BudgetPlan.id).filter(
        models.BudgetPlan.id == plan_id,
        models.BudgetPlan.client_id == client_id,
    ).first()
    if not exists:
        raise ValueError("Budget plan not found")
    return plan_id


def period_to_range(period: str) -> tuple[date, date]:
    year, month = [int(part) for part in period.split("-")]
    start = date(year, month, 1)
    end = start + relativedelta(months=1)
    return start, end


def add_months(period: str, months: int) -> str:
    start, _ = period_to_range(period)
    shifted = start + relativedelta(months=months)
    return f"{shifted.year}-{shifted.month:02d}"


def period_months_between(start_period: str, end_period: str) -> list[str]:
    start, _ = period_to_range(start_period)
    end, _ = period_to_range(end_period)
    periods = []
    cursor = start
    while cursor <= end:
        periods.append(f"{cursor.year}-{cursor.month:02d}")
        cursor += relativedelta(months=1)
    return periods


def current_period_key(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year}-{today.month:02d}"




def _target_name_maps(db: Session, client_id: int) -> dict[str, dict[int, str]]:
    accounts = db.query(models.Account).filter(models.Account.client_id == client_id).all()
    capsules = db.query(models.Capsule).filter(models.Capsule.client_id == client_id).all()
    life_events = db.query(models.LifeEvent).filter(models.LifeEvent.client_id == client_id).all()
    products = db.query(models.Product).filter(models.Product.client_id == client_id).all()
    return {
        "account": {item.id: item.name for item in accounts},
        "capsule": {item.id: item.name for item in capsules},
        "life_event": {item.id: item.name for item in life_events},
        "product": {item.id: item.name for item in products},
    }


def _line_display_name(line: models.MonthlyPlanLine, name_maps: dict[str, dict[int, str]]) -> str:
    if line.name:
        return line.name
    if line.target_type == "account" and line.account_id:
        return name_maps["account"].get(line.account_id, "Account")
    if line.target_id:
        return name_maps.get(line.target_type, {}).get(line.target_id, line.target_type.title())
    return line.line_type.replace("_", " ").title()


def _period_transactions(db: Session, client_id: int, period: str) -> list[models.Transaction]:
    start, end = period_to_range(period)
    return db.query(models.Transaction).filter(
        models.Transaction.client_id == client_id,
        models.Transaction.date >= start,
        models.Transaction.date < end,
    ).all()


def _sum_transactions(txs: Iterable[models.Transaction], db: Session, client_id: int) -> float:
    return sum(convert_transaction_amount(db, tx, client_id=client_id) for tx in txs)


def actual_for_plan_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    period: str,
    capsule_accounts: dict[int, int | None] | None = None,
    context: BudgetSummaryContext | None = None,
) -> float:
    capsule_accounts = capsule_accounts or {}
    txs = _period_transactions_cached(db, client_id, period, context)
    line_type = line["line_type"] if isinstance(line, dict) else line.line_type
    target_type = line["target_type"] if isinstance(line, dict) else line.target_type
    target_id = line.get("target_id") if isinstance(line, dict) else line.target_id
    account_id = line.get("account_id") if isinstance(line, dict) else line.account_id
    name = (line.get("name") if isinstance(line, dict) else line.name) or ""
    needle = name.lower()

    if target_type == "capsule" and target_id:
        capsule = (context or {}).get("capsule_by_id", {}).get(target_id)
        if capsule is None:
            capsule = db.query(models.Capsule).filter(
                models.Capsule.id == target_id,
                models.Capsule.client_id == client_id,
            ).first()
        if capsule:
            cached_balances = (context or {}).get("capsule_balances", {})
            return cached_balances.get(capsule.id, capsule_balance(db, capsule))
        account_id = capsule_accounts.get(target_id)

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
    return _sum_transactions(selected, db, client_id)


def _line_attr(line: models.MonthlyPlanLine | dict, key: str):
    if isinstance(line, dict):
        return line.get(key)
    return getattr(line, key, None)


def _line_cash_treatment(line: models.MonthlyPlanLine | dict) -> str:
    return _line_attr(line, "cash_treatment") or "auto"


def _line_source_kind(line: models.MonthlyPlanLine | dict) -> str:
    explicit = _line_attr(line, "source_kind")
    if explicit:
        if explicit == "recurrence":
            return "recurring"
        return explicit
    source = _line_attr(line, "source")
    recurring_id = _line_attr(line, "recurring_transaction_id")
    if recurring_id:
        return "recurring"
    if source and source != "manual":
        if source == "recurrence":
            return "recurring"
        return source
    target_type = _line_attr(line, "target_type")
    if target_type in {"capsule", "product"} and _line_attr(line, "target_id"):
        return target_type
    return "manual"


def _line_source_id(line: models.MonthlyPlanLine | dict) -> int | None:
    explicit = _line_attr(line, "source_id")
    if explicit:
        return explicit
    recurring_id = _line_attr(line, "recurring_transaction_id")
    if recurring_id:
        return recurring_id
    target_type = _line_attr(line, "target_type")
    target_id = _line_attr(line, "target_id")
    if target_type in {"capsule", "product"} and target_id:
        return target_id
    if _line_source_kind(line) == "credit_settlement":
        return _line_attr(line, "account_id")
    return None


def _linked_recurring_transaction_type(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    context: BudgetSummaryContext | None = None,
) -> str | None:
    transaction_type = _line_attr(line, "transaction_type")
    if transaction_type:
        return transaction_type
    recurring_id = _line_attr(line, "recurring_transaction_id")
    if not recurring_id:
        return None
    if context is not None:
        cache = context.setdefault("recurring_transaction_types", {})
        if recurring_id in cache:
            return cache[recurring_id]
    recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == client_id,
    ).first()
    transaction_type = recurring.type if recurring else None
    if context is not None:
        context.setdefault("recurring_transaction_types", {})[recurring_id] = transaction_type
    return transaction_type


def _account_cache(db: Session, client_id: int, context: BudgetSummaryContext | None = None) -> dict[int, models.Account]:
    if context is not None:
        cache = context.setdefault("account_by_id", {})
        if client_id not in cache:
            cache[client_id] = {
                account.id: account
                for account in db.query(models.Account).filter(models.Account.client_id == client_id).all()
            }
        return cache[client_id]
    return {
        account.id: account
        for account in db.query(models.Account).filter(models.Account.client_id == client_id).all()
    }


def _account_by_id(
    db: Session,
    client_id: int,
    account_id: int | None,
    context: BudgetSummaryContext | None = None,
) -> models.Account | None:
    if not account_id:
        return None
    return _account_cache(db, client_id, context).get(account_id)


def account_flow_bucket(account: models.Account | None) -> str:
    if not account:
        return "unknown"
    if account.account_type == "asset":
        name = (account.name or "").strip().lower()
        role = account.role or "unassigned"
        if role == "operating" or name in LIQUID_ACCOUNT_NAMES:
            return "operating"
        if role in {"defense", "earmarked", "growth"}:
            return role
        return "unassigned"
    if account.account_type in {"liability", "income", "expense"}:
        return account.account_type
    return "unknown"


def _empty_flow() -> dict[str, float]:
    return {
        "inflow": 0.0,
        "expense": 0.0,
        "allocation": 0.0,
        "debt": 0.0,
        "operating": 0.0,
        "defense": 0.0,
        "earmarked": 0.0,
        "growth": 0.0,
        "unassigned": 0.0,
        "financing": 0.0,
        "internal_transfer": 0.0,
        "non_cash_budget": 0.0,
    }


def _empty_balance() -> dict[str, float]:
    return {
        "operating": 0.0,
        "defense": 0.0,
        "earmarked": 0.0,
        "growth": 0.0,
        "unassigned": 0.0,
        "liabilities": 0.0,
    }


def _add_flow(target: dict[str, float], source: dict[str, float]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0.0) + (value or 0.0)


def _movement_flow(from_bucket: str, to_bucket: str, amount: float) -> dict[str, float]:
    flow = _empty_flow()
    if amount <= 0:
        return flow

    if from_bucket in ASSET_FLOW_BUCKETS:
        flow[from_bucket] -= amount
    if to_bucket in ASSET_FLOW_BUCKETS:
        flow[to_bucket] += amount

    if from_bucket == "operating" and to_bucket == "expense":
        flow["expense"] += amount
    elif from_bucket == "operating" and to_bucket == "liability":
        flow["debt"] += amount
        flow["financing"] -= amount
    elif from_bucket == "liability" and to_bucket in ASSET_FLOW_BUCKETS:
        flow["inflow"] += amount if to_bucket == "operating" else 0.0
        flow["financing"] += amount
    elif from_bucket == "income" and to_bucket in ASSET_FLOW_BUCKETS:
        flow["inflow"] += amount if to_bucket == "operating" else 0.0
    elif from_bucket == "operating" and to_bucket in {"defense", "earmarked", "growth", "unassigned"}:
        flow["allocation"] += amount
    elif from_bucket in {"defense", "earmarked", "growth", "unassigned"} and to_bucket == "operating":
        flow["inflow"] += amount
    elif from_bucket == "operating" and to_bucket == "operating":
        flow["internal_transfer"] += amount
    elif from_bucket in ASSET_FLOW_BUCKETS and to_bucket in ASSET_FLOW_BUCKETS:
        flow["internal_transfer"] += amount
    elif from_bucket == "liability" and to_bucket == "expense":
        flow["non_cash_budget"] += amount

    return flow


def _fallback_line_flow(line_type: str | None, amount: float) -> dict[str, float]:
    flow = _empty_flow()
    if amount <= 0:
        return flow
    if line_type in INFLOW_LINE_TYPES:
        flow["inflow"] = amount
        flow["operating"] = amount
        if line_type == "borrowing":
            flow["financing"] = amount
    elif line_type == "expense":
        flow["expense"] = amount
        flow["operating"] = -amount
    elif line_type == "allocation":
        flow["allocation"] = amount
        flow["operating"] = -amount
    elif line_type == "debt_payment":
        flow["debt"] = amount
        flow["operating"] = -amount
        flow["financing"] = -amount
    return flow


def plan_line_has_cash_impact(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    context: BudgetSummaryContext | None = None,
) -> bool:
    treatment = _line_cash_treatment(line)
    if treatment == "cash":
        return True
    if treatment == "non_cash":
        return False
    return _linked_recurring_transaction_type(db, client_id, line, context) not in NON_CASH_TRANSACTION_TYPES


def _cash_flow_line_account_id(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    context: BudgetSummaryContext | None = None,
) -> int | None:
    account_id = _line_attr(line, "account_id")
    if account_id:
        return account_id

    target_type = _line_attr(line, "target_type")
    target_id = _line_attr(line, "target_id")
    if target_type == "capsule" and target_id:
        capsule_by_id = (context or {}).get("capsule_by_id", {})
        capsule = capsule_by_id.get(target_id)
        if capsule is None:
            capsule = db.query(models.Capsule).filter(
                models.Capsule.id == target_id,
                models.Capsule.client_id == client_id,
            ).first()
        return capsule.account_id if capsule else None

    if target_type == "life_event" and target_id:
        capsule_by_life_event_id = (context or {}).get("capsule_by_life_event_id", {})
        capsule = capsule_by_life_event_id.get(target_id)
        if capsule is None:
            capsule = db.query(models.Capsule).filter(
                models.Capsule.client_id == client_id,
                models.Capsule.life_event_id == target_id,
            ).first()
        return capsule.account_id if capsule else None

    return None


def _registry_line_for_plan_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    context: BudgetSummaryContext | None = None,
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
    for registry_line in registry_plan_lines(db, client_id, period, context):
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
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    context: BudgetSummaryContext | None = None,
) -> int | None:
    source_account_id = _line_attr(line, "source_account_id")
    if source_account_id:
        return source_account_id
    registry_line = _registry_line_for_plan_line(db, client_id, line, context)
    return registry_line.get("source_account_id") if registry_line else None


def _plan_line_movement_accounts(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    context: BudgetSummaryContext | None = None,
) -> tuple[models.Account | None, models.Account | None]:
    line_type = _line_attr(line, "line_type")
    source_account = _account_by_id(db, client_id, _cash_flow_line_source_account_id(db, client_id, line, context), context)
    target_account = _account_by_id(db, client_id, _cash_flow_line_account_id(db, client_id, line, context), context)

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
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    amount: float,
    context: BudgetSummaryContext | None = None,
) -> dict[str, float]:
    if amount <= 0:
        return _empty_flow()
    treatment = _line_cash_treatment(line)
    if treatment == "non_cash":
        flow = _empty_flow()
        flow["non_cash_budget"] = amount
        return flow

    from_account, to_account = _plan_line_movement_accounts(db, client_id, line, context)
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
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    amount: float,
    context: BudgetSummaryContext | None = None,
) -> dict[str, float]:
    movement = _empty_balance()
    if amount <= 0:
        return movement

    from_account, to_account = _plan_line_movement_accounts(db, client_id, line, context)
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
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    period: str,
    context: BudgetSummaryContext | None = None,
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
    if plan_line_has_cash_impact(db, client_id, line, context):
        actual = cash_flow_actual_for_plan_line(db, client_id, line, period, context)
    else:
        actual = actual_for_plan_line(db, client_id, line, period, context=context)
    remaining = max(0.0, planned - actual)
    projected = actual + remaining
    return projected, actual, remaining


def cash_flow_actual_for_plan_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    period: str,
    context: BudgetSummaryContext | None = None,
) -> float:
    """Return transactions already executed for a plan line in a cash-flow period.

    This intentionally differs from actual_for_plan_line: capsule budget rows use
    current capsule balance for budget variance, but cash flow only needs the
    already-executed movement for the month.
    """
    if not plan_line_has_cash_impact(db, client_id, line, context):
        return 0.0
    txs = _period_transactions_cached(db, client_id, period, context)
    line_type = _line_attr(line, "line_type")
    account_id = _cash_flow_line_account_id(db, client_id, line, context)
    source_account_id = _cash_flow_line_source_account_id(db, client_id, line, context)
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
    return _sum_transactions(selected, db, client_id)


def _cash_flow_line_amount_for_period(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine,
    period: str,
    context: BudgetSummaryContext | None = None,
) -> float:
    planned = line.amount or 0.0
    if period != current_period_key():
        return planned
    if not plan_line_has_cash_impact(db, client_id, line, context):
        return planned
    actual = cash_flow_actual_for_plan_line(db, client_id, line, period, context)
    return max(0.0, planned - actual)


def _serialize_plan_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine,
    name_maps: dict[str, dict[int, str]],
    capsule_accounts: dict[int, int | None],
    context: BudgetSummaryContext | None = None,
) -> dict:
    actual = actual_for_plan_line(db, client_id, line, line.target_period, capsule_accounts, context)
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
    db: Session,
    client_id: int,
    capsule: models.Capsule,
    period: str,
    capsule_accounts: dict[int, int | None],
    context: BudgetSummaryContext | None = None,
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
        "suggested_items": product_reserve_source_items(db, capsule) if capsule.capsule_type == "product_pool" else [],
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
    actual = actual_for_plan_line(db, client_id, line, period, capsule_accounts, context)
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


def _attach_capsule_suggestions(db: Session, plan_lines: list[dict], capsule_by_id: dict[int, models.Capsule]) -> None:
    for line in plan_lines:
        if line.get("line_type") != "allocation" or line.get("target_type") != "capsule":
            continue
        capsule = capsule_by_id.get(line.get("target_id"))
        if not capsule or capsule.capsule_type != "product_pool":
            continue
        suggested = round(capsule.monthly_contribution or 0.0, 0)
        line["suggested_amount"] = suggested
        line["suggested_source"] = "product_reserve"
        line["suggested_items"] = product_reserve_source_items(db, capsule)
        line["suggested_status"] = (
            "synced"
            if line.get("source") == "capsule" and round(line.get("amount") or 0.0, 0) == suggested
            else "diff"
        )


def _sum_lines(lines: Iterable[dict], *line_types: str) -> float:
    wanted = set(line_types)
    return sum((line.get("amount") or 0.0) for line in lines if line.get("line_type") in wanted)


def _sum_actual(lines: Iterable[dict], *line_types: str) -> float:
    wanted = set(line_types)
    return sum((line.get("actual") or 0.0) for line in lines if line.get("line_type") in wanted)


def _plan_match_key(
    line_type: str | None,
    target_type: str | None,
    account_id: int | None,
    name: str | None,
    source_account_id: int | None = None,
    cash_treatment: str | None = "auto",
) -> tuple:
    normalized_name = "" if account_id else (name or "").strip().lower()
    return (
        line_type or "",
        target_type or "manual",
        account_id or 0,
        source_account_id or 0,
        normalized_name,
        cash_treatment or "auto",
    )


def _line_identity_key(line: models.MonthlyPlanLine | dict) -> tuple:
    getter = line.get if isinstance(line, dict) else lambda key, default=None: getattr(line, key, default)
    account_id = getter("account_id")
    target_id = getter("target_id")
    name = "" if account_id or target_id else (getter("name") or "").strip().lower()
    source_kind = _line_source_kind(line)
    source_id = _line_source_id(line) or 0
    return (
        getter("plan_id") or 0,
        getter("target_period"),
        source_kind,
        source_id,
        getter("line_type"),
        getter("target_type") or "manual",
        account_id or 0,
        getter("source_account_id") or 0,
        target_id or 0,
        name,
        getter("cash_treatment", "auto") or "auto",
    )


def plan_line_identity_key(line: models.MonthlyPlanLine | dict) -> str:
    return json.dumps(_line_identity_key(line), ensure_ascii=True, separators=(",", ":"))


def assign_plan_line_identity(line: models.MonthlyPlanLine) -> None:
    line.source_kind = _line_source_kind(line)
    if line.source_id is None:
        line.source_id = _line_source_id(line)
    line.identity_key = plan_line_identity_key(line)


def _newest_line_key(line: models.MonthlyPlanLine) -> tuple:
    return (
        line.updated_at or line.created_at or datetime.min,
        line.created_at or datetime.min,
        line.id or 0,
    )


def _deduplicate_active_plan_models(
    db: Session,
    plan_models: list[models.MonthlyPlanLine],
    *,
    repair: bool = False,
) -> list[models.MonthlyPlanLine]:
    grouped: dict[tuple, list[models.MonthlyPlanLine]] = {}
    for line in plan_models:
        grouped.setdefault(_line_identity_key(line), []).append(line)

    deduped: list[models.MonthlyPlanLine] = []
    changed = False
    for lines in grouped.values():
        if len(lines) == 1:
            deduped.append(lines[0])
            continue
        keeper = max(lines, key=_newest_line_key)
        deduped.append(keeper)
        for duplicate in lines:
            if duplicate.id != keeper.id:
                if repair:
                    duplicate.is_active = False
                    changed = True

    if repair and changed:
        db.commit()
    return sorted(deduped, key=lambda line: (line.line_type, line.id))


def _active_line_with_identity(
    db: Session,
    client_id: int,
    data: dict,
    exclude_id: int | None = None,
) -> models.MonthlyPlanLine | None:
    key = _line_identity_key({**data, "target_period": data.get("target_period")})
    q = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.target_period == data.get("target_period"),
        models.MonthlyPlanLine.line_type == data.get("line_type"),
        models.MonthlyPlanLine.is_active.is_(True),
    )
    plan_id = data.get("plan_id")
    if plan_id is not None:
        q = q.filter(models.MonthlyPlanLine.plan_id == plan_id)
    rows = q.all()
    return next((line for line in rows if line.id != exclude_id and _line_identity_key(line) == key), None)


def _active_duplicate_for_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine,
) -> models.MonthlyPlanLine | None:
    return _active_line_with_identity(
        db,
        client_id,
        {
            "plan_id": line.plan_id,
            "target_period": line.target_period,
            "source_kind": _line_source_kind(line),
            "source_id": _line_source_id(line),
            "line_type": line.line_type,
            "target_type": line.target_type,
            "target_id": line.target_id,
            "account_id": line.account_id,
            "source_account_id": line.source_account_id,
            "name": line.name,
            "cash_treatment": line.cash_treatment,
        },
        exclude_id=line.id,
    )




def _registry_plan_line(
    db: Session,
    entry: models.RegistryEntry,
    period: str,
    name_maps: dict[str, dict[int, str]],
) -> dict | None:
    period_start, _ = period_to_range(period)
    amount = registry_entry_amount_for_period(db, entry, period, period_start, entry.client_id)
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


def _virtual_registry_entries(
    db: Session,
    client_id: int,
    existing_entries: list[models.RegistryEntry],
) -> list[SimpleNamespace]:
    existing_product_ids = {
        entry.source_product_id
        for entry in existing_entries
        if entry.source_product_id
    }
    existing_recurring_ids = {
        entry.source_recurring_transaction_id
        for entry in existing_entries
        if entry.source_recurring_transaction_id
    }
    entries: list[SimpleNamespace] = []

    products = db.query(models.Product).filter(models.Product.client_id == client_id).all()
    for product in products:
        if product.id in existing_product_ids or not product_budget_active(product):
            continue
        entries.append(SimpleNamespace(
            id=-product.id,
            client_id=client_id,
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

    recurring_rows = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == client_id,
        models.RecurringTransaction.is_active.is_(True),
    ).all()
    for recurring in recurring_rows:
        if recurring.id in existing_recurring_ids:
            continue
        line_type = recurring_line_type(recurring.type)
        entries.append(SimpleNamespace(
            id=-(1000000 + recurring.id),
            client_id=client_id,
            name=recurring.name,
            entry_type=recurring_entry_type(recurring.type),
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


def registry_plan_lines(
    db: Session,
    client_id: int,
    period: str,
    context: BudgetSummaryContext | None = None,
) -> list[dict]:
    if context is not None:
        cache = context.setdefault("registry_lines", {})
        if period in cache:
            return cache[period]
        maps_cache = context.setdefault("target_name_maps", {})
        if client_id not in maps_cache:
            maps_cache[client_id] = _target_name_maps(db, client_id)
        name_maps = maps_cache[client_id]
    else:
        name_maps = _target_name_maps(db, client_id)
    entries = db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == client_id,
        models.RegistryEntry.is_active.is_(True),
        models.RegistryEntry.budget_active.is_(True),
    ).all()
    entries = [*entries, *_virtual_registry_entries(db, client_id, entries)]
    lines = [line for entry in entries if (line := _registry_plan_line(db, entry, period, name_maps)) is not None]
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
    result = list(aggregated.values())
    if context is not None:
        cache[period] = result
    return result


def registry_totals(
    db: Session,
    client_id: int,
    period: str,
    context: BudgetSummaryContext | None = None,
) -> dict[str, float]:
    totals = {
        "income": 0.0,
        "fixed_costs": 0.0,
        "debt_payments": 0.0,
        "allocations": 0.0,
        "borrowing": 0.0,
    }
    for line in registry_plan_lines(db, client_id, period, context):
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


def _credit_settlement_plan_line(
    db: Session,
    client_id: int,
    account: models.Account,
    period: str,
    amount: float,
    context: BudgetSummaryContext | None = None,
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
    actual = cash_flow_actual_for_plan_line(db, client_id, line, period, context)
    line["actual"] = round(actual, 0)
    line["variance"] = round(amount - actual, 0)
    return line


def _account_has_liability_schedule(account: models.Account) -> bool:
    return bool(
        account.liability_closing_day
        or account.liability_payment_day
        or (account.liability_payment_month_offset or 0) > 0
    )


def _statement_period_for_liability(account: models.Account, activity_date: date) -> str:
    period = f"{activity_date.year}-{activity_date.month:02d}"
    closing_day = account.liability_closing_day
    if closing_day and activity_date.day > closing_day:
        period = add_months(period, 1)
    return period


def _settlement_period_for_liability(account: models.Account, activity_date: date) -> str:
    offset = max(0, int(account.liability_payment_month_offset or 0))
    return add_months(_statement_period_for_liability(account, activity_date), offset)


def _liability_activity_allocations(account: models.Account, activity_date: date, amount: float) -> list[tuple[str, float]]:
    amount = max(0.0, amount or 0.0)
    if amount <= 0:
        return []
    first_period = _settlement_period_for_liability(account, activity_date)
    if (account.liability_payment_policy or "full") == "installment":
        months = max(1, int(account.liability_installment_months or 1))
        installment_amount = amount / months
        return [(add_months(first_period, index), installment_amount) for index in range(months)]
    return [(first_period, amount)]


def _last_day_of_month(period: str) -> int:
    start, _ = period_to_range(period)
    return (start + relativedelta(day=31)).day


def _recurring_activity_date(row: models.RecurringTransaction, period: str) -> date:
    start, _ = period_to_range(period)
    day = min(max(1, row.day_of_month or 1), _last_day_of_month(period))
    return date(start.year, start.month, day)


def _recurring_applies_to_period(row: models.RecurringTransaction, period: str) -> bool:
    if row.start_period and row.start_period > period:
        return False
    if row.end_period and row.end_period < period:
        return False
    if row.frequency == "Yearly":
        month = int(period.split("-")[1])
        return not row.month_of_year or row.month_of_year == month
    return True


def _apply_liability_payment_policy(account: models.Account, amount: float) -> float:
    amount = max(0.0, amount or 0.0)
    if amount <= 0:
        return 0.0
    policy = account.liability_payment_policy or "full"
    minimum = max(0.0, account.liability_minimum_payment or 0.0)
    if policy == "minimum":
        return min(amount, minimum or amount)
    if policy == "fixed":
        fixed = max(0.0, account.liability_fixed_payment_amount or 0.0)
        return min(amount, fixed or amount)
    if policy == "installment":
        return amount
    if policy == "revolving":
        rate_amount = amount * max(0.0, account.liability_revolving_rate or 0.0) / 100
        payment = max(minimum, rate_amount)
        return min(amount, payment or amount)
    return amount


def credit_settlement_plan_lines(
    db: Session,
    client_id: int,
    period: str,
    context: BudgetSummaryContext | None = None,
) -> list[dict]:
    if context is not None:
        cache = context.setdefault("credit_settlement_lines", {})
        if period in cache:
            return cache[period]

    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "liability",
        models.Account.is_active.is_(True),
    ).all()
    accounts_by_id = {account.id: account for account in accounts}
    if not accounts_by_id:
        result: list[dict] = []
        if context is not None:
            cache[period] = result
        return result

    max_offset = max((account.liability_payment_month_offset or 0) for account in accounts)
    max_installment_months = max((account.liability_installment_months or 1) for account in accounts)
    search_start_period = add_months(period, -(max_offset + max_installment_months + 1))
    search_start, _ = period_to_range(search_start_period)
    _, search_end = period_to_range(period)
    txs = db.query(models.Transaction).filter(
        models.Transaction.client_id == client_id,
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
        tx_amount = convert_transaction_amount(db, tx, client_id=client_id)
        for settlement_period, amount in _liability_activity_allocations(account, tx.date, tx_amount):
            if settlement_period == period:
                credit_usage_by_account[tx.from_account_id] = credit_usage_by_account.get(tx.from_account_id, 0.0) + amount

    recurring_credit_by_account: dict[int, float] = {}
    recurring_rows = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == client_id,
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
            recurring_amount = convert_amount(db, client_id, row.amount or 0.0, row.currency or "JPY", as_of_date=activity_date)
            for settlement_period, amount in _liability_activity_allocations(account, activity_date, recurring_amount):
                if settlement_period == period:
                    recurring_credit_by_account[row.from_account_id] = (
                        recurring_credit_by_account.get(row.from_account_id, 0.0)
                        + amount
                    )
    account_ids = set(credit_usage_by_account) | set(recurring_credit_by_account)
    if not account_ids:
        result: list[dict] = []
        if context is not None:
            cache[period] = result
        return result

    result = []
    for account_id in account_ids:
        account = accounts_by_id.get(account_id)
        if not account:
            continue
        balance = max(0.0, calculate_account_valued_balance(db, account))
        activity_amount = credit_usage_by_account.get(account.id, 0.0) + recurring_credit_by_account.get(account.id, 0.0)
        if _account_has_liability_schedule(account):
            raw_amount = activity_amount if activity_amount > 0 else (balance if (account.liability_payment_month_offset or 0) == 0 else 0.0)
        else:
            raw_amount = max(balance, activity_amount)
        amount = _apply_liability_payment_policy(account, raw_amount)
        if amount > 0:
            result.append(_credit_settlement_plan_line(db, client_id, account, period, amount, context))
    if context is not None:
        cache[period] = result
    return result


def _merge_registry_context(plan_lines: list[dict], registry_lines: list[dict]) -> list[dict]:
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


def _merge_credit_settlement_context(plan_lines: list[dict], settlement_lines: list[dict]) -> list[dict]:
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


def _plan_line_matches_registry_line(line: models.MonthlyPlanLine | dict, registry_line: dict) -> bool:
    if _line_attr(line, "line_type") != registry_line.get("line_type"):
        return False
    if (_line_attr(line, "cash_treatment") or "auto") != (registry_line.get("cash_treatment") or "auto"):
        return False
    line_account_id = _line_attr(line, "account_id")
    registry_account_id = registry_line.get("account_id")
    if line_account_id and registry_account_id and line_account_id == registry_account_id:
        return True
    if line_account_id != registry_account_id:
        return False
    line_name = (_line_attr(line, "name") or _line_attr(line, "target_name") or "").strip().lower()
    registry_names = {
        (registry_line.get("name") or "").strip().lower(),
        (registry_line.get("target_name") or "").strip().lower(),
    }
    registry_names.update(
        (item.get("name") or "").strip().lower()
        for item in registry_line.get("registry_items", [])
    )
    return bool(line_name and line_name in registry_names)


def _liquid_cash(db: Session, client_id: int) -> float:
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "asset",
        models.Account.is_active.is_(True),
        or_(models.Account.name.in_(LIQUID_ACCOUNT_NAMES), models.Account.role == "operating"),
    ).all()
    return sum(calculate_account_valued_balance(db, account) for account in accounts)


def _starting_balance_state(db: Session, client_id: int) -> dict[str, float]:
    state = _empty_balance()
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.is_active.is_(True),
    ).all()
    for account in accounts:
        balance = calculate_account_valued_balance(db, account)
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


def get_budget_summary(
    db: Session,
    client_id: int,
    period: str,
    plan_id: int | None = None,
    cash_flow_start_period: str | None = None,
    cash_flow_months: int = 12,
) -> dict:
    context: BudgetSummaryContext = {}
    plan_id = resolve_budget_plan_id(db, client_id, plan_id)

    events_with_progress = get_life_events_with_progress(db, client_id=client_id)
    total_gap = sum(max(0, e["gap"]) for e in events_with_progress)
    avg_years = (
        sum(e["years_remaining"] for e in events_with_progress) / len(events_with_progress)
        if events_with_progress else 10
    )
    required_monthly_savings = total_gap / (avg_years * 12) if avg_years > 0 else 0

    recurring = registry_totals(db, client_id, period, context)
    name_maps = _target_name_maps(db, client_id)
    capsules = db.query(models.Capsule).filter(models.Capsule.client_id == client_id).all()
    capsule_accounts = {capsule.id: capsule.account_id for capsule in capsules}
    capsule_by_id = {capsule.id: capsule for capsule in capsules}
    context["capsule_by_id"] = capsule_by_id
    context["capsule_balances"] = {capsule.id: capsule_balance(db, capsule) for capsule in capsules}
    capsule_by_life_event_id = {
        capsule.life_event_id: capsule
        for capsule in capsules
        if capsule.life_event_id
    }
    context["capsule_by_life_event_id"] = capsule_by_life_event_id

    plan_models = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.target_period == period,
        models.MonthlyPlanLine.is_active.is_(True),
        models.MonthlyPlanLine.plan_id == plan_id,
    ).order_by(models.MonthlyPlanLine.line_type, models.MonthlyPlanLine.id).all()
    plan_models = _deduplicate_active_plan_models(db, plan_models)
    plan_lines = [
        _serialize_plan_line(db, client_id, line, name_maps, capsule_accounts, context)
        for line in plan_models
    ]
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
                actual = actual_for_plan_line(db, client_id, line, period, capsule_accounts, context)
                line["actual"] = round(actual, 0)
                line["variance"] = round((line.get("amount") or 0.0) - actual, 0)

    _attach_capsule_suggestions(db, plan_lines, capsule_by_id)
    existing_capsule_ids = {
        line.get("target_id")
        for line in plan_lines
        if line.get("line_type") == "allocation" and line.get("target_type") == "capsule"
    }
    for capsule in capsules:
        if capsule.id not in existing_capsule_ids:
            plan_lines.append(_virtual_capsule_line(db, client_id, capsule, period, capsule_accounts, context))
    plan_lines = _merge_registry_context(plan_lines, registry_plan_lines(db, client_id, period, context))
    plan_lines = _merge_credit_settlement_context(plan_lines, credit_settlement_plan_lines(db, client_id, period, context))

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
    starting_cash = _liquid_cash(db, client_id)
    minimum_operating_cash = 0.0
    ending_cash_after_plan = starting_cash + remaining
    feasibility_status = "ok"
    if remaining < 0:
        feasibility_status = "warning"
    if ending_cash_after_plan < minimum_operating_cash:
        feasibility_status = "shortfall"

    projection_start = cash_flow_start_period or period
    projection = get_cash_flow_projection(db, client_id, projection_start, months=cash_flow_months, starting_cash=starting_cash, plan_id=plan_id, context=context)
    cash_flow_summary = summarize_cash_flow_projection(projection, starting_cash, projection_start)
    balance_projection = get_balance_projection(db, client_id, projection_start, months=cash_flow_months, plan_id=plan_id, context=context)
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
        "minimum_operating_cash": round(minimum_operating_cash, 0),
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
                    capsule_balance(db, capsule)
                    if (capsule := next((c for c in capsules if c.id == line.get("target_id")), None))
                    else 0.0,
                    0,
                ),
                "target_amount": round(
                    capsule.target_amount if (capsule := next((c for c in capsules if c.id == line.get("target_id")), None)) else 0.0,
                    0,
                ),
            }
            for line in capsule_lines
        ],
        "cash_flow_projection": projection,
        "cash_flow_summary": cash_flow_summary,
        "balance_projection": balance_projection,
        "balance_summary": balance_summary,
        "goals_count": len(events_with_progress),
        "total_goal_gap": round(total_gap, 0),
    }


def get_cash_flow_projection(
    db: Session,
    client_id: int,
    start_period: str,
    months: int = 12,
    starting_cash: float | None = None,
    plan_id: int | None = None,
    context: BudgetSummaryContext | None = None,
) -> list[dict]:
    plan_id = resolve_budget_plan_id(db, client_id, plan_id)
    cash = _liquid_cash(db, client_id) if starting_cash is None else starting_cash
    rows = []
    for idx in range(months):
        period = add_months(start_period, idx)
        q = db.query(models.MonthlyPlanLine).filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.target_period == period,
            models.MonthlyPlanLine.is_active.is_(True),
            models.MonthlyPlanLine.plan_id == plan_id,
        )
        lines = q.all()
        lines = _deduplicate_active_plan_models(db, lines)
        projection_lines: list[models.MonthlyPlanLine | dict] = list(lines)
        planned_flow = _empty_flow()
        actual_flow = _empty_flow()
        remaining_flow = _empty_flow()
        for line in projection_lines:
            planned_amount, actual_amount, remaining_amount = _projection_amounts_for_period(db, client_id, line, period, context)
            _add_flow(planned_flow, plan_line_flow_for_amount(db, client_id, line, planned_amount, context))
            _add_flow(actual_flow, plan_line_flow_for_amount(db, client_id, line, actual_amount, context))
            _add_flow(remaining_flow, plan_line_flow_for_amount(db, client_id, line, remaining_amount, context))
        income = remaining_flow["inflow"]
        expense = remaining_flow["expense"]
        allocation = remaining_flow["allocation"]
        debt = remaining_flow["debt"]
        net = remaining_flow["operating"]
        cash += net
        setup_warnings = budget_setup_warnings(db, client_id, period, lines, context)
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
    context: BudgetSummaryContext | None = None,
) -> list[dict]:
    plan_id = resolve_budget_plan_id(db, client_id, plan_id)
    state = _starting_balance_state(db, client_id)
    rows = []
    for idx in range(months):
        period = add_months(start_period, idx)
        lines = (
            db.query(models.MonthlyPlanLine)
            .filter(
                models.MonthlyPlanLine.client_id == client_id,
                models.MonthlyPlanLine.target_period == period,
                models.MonthlyPlanLine.is_active.is_(True),
                models.MonthlyPlanLine.plan_id == plan_id,
            )
            .all()
        )
        lines = _deduplicate_active_plan_models(db, lines)
        projection_lines: list[models.MonthlyPlanLine | dict] = list(lines)
        for line in projection_lines:
            _, _, remaining_amount = _projection_amounts_for_period(db, client_id, line, period, context)
            movement = _balance_movement_for_amount(db, client_id, line, remaining_amount, context)
            for key, value in movement.items():
                state[key] = state.get(key, 0.0) + (value or 0.0)
        rows.append(_balance_projection_row(period, state))
    return rows


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


def budget_setup_warnings(
    db: Session,
    client_id: int,
    period: str,
    plan_models: list[models.MonthlyPlanLine],
    context: BudgetSummaryContext | None = None,
) -> list[dict]:
    return [
        *recurrence_setup_warnings(db, client_id, period, plan_models, context),
        *credit_settlement_setup_warnings(db, client_id, period, plan_models, context),
        *product_reserve_setup_warnings(db, client_id, plan_models),
    ]


def recurrence_setup_warnings(
    db: Session,
    client_id: int,
    period: str,
    plan_models: list[models.MonthlyPlanLine],
    context: BudgetSummaryContext | None = None,
) -> list[dict]:
    registry_lines = registry_plan_lines(db, client_id, period, context)
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
    db: Session,
    client_id: int,
    plan_models: list[models.MonthlyPlanLine],
) -> list[dict]:
    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id,
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
    db: Session,
    client_id: int,
    period: str,
    plan_models: list[models.MonthlyPlanLine],
    context: BudgetSummaryContext | None = None,
) -> list[dict]:
    plan_by_account = {
        line.account_id: line
        for line in plan_models
        if line.line_type == "debt_payment" and line.account_id is not None
    }
    warnings = []
    for settlement in credit_settlement_plan_lines(db, client_id, period, context):
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


def _payload_data(payload) -> dict:
    return payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)


def _apply_plan_line_data(db: Session, client_id: int, line: models.MonthlyPlanLine, data: dict) -> None:
    for key, value in data.items():
        if key != "id":
            setattr(line, key, value)
    line.source_kind = _line_source_kind(line)
    if line.source_id is None:
        line.source_id = _line_source_id(line)
    if line.source == "manual":
        line.source_kind = "manual"
        line.source_id = None
    # Normalize manual lines: if no account_id is set but the registry has one for
    # this line_type+name, promote target_type to "account" so future matching works.
    if (not line.account_id) and line.target_type in (None, "manual") and line.name and line.line_type:
        registry_entry = db.query(models.RegistryEntry).filter(
            models.RegistryEntry.client_id == client_id,
            models.RegistryEntry.is_active.is_(True),
            models.RegistryEntry.name == line.name,
            models.RegistryEntry.line_type == line.line_type,
        ).first()
        if registry_entry:
            resolved = registry_target_account_id(registry_entry)
            if resolved:
                line.account_id = resolved
                line.target_type = "account"
    if line.target_type == "account" and line.account_id and not line.name:
        account = db.query(models.Account).filter(
            models.Account.id == line.account_id,
            models.Account.client_id == client_id,
        ).first()
        if account:
            line.name = account.name
    if line.target_type == "capsule" and line.target_id:
        capsule = db.query(models.Capsule).filter(
            models.Capsule.id == line.target_id,
            models.Capsule.client_id == client_id,
        ).first()
        if capsule:
            line.name = capsule.name
            line.account_id = capsule.account_id
            capsule.monthly_contribution = line.amount or 0.0
            if line.source in {None, "manual", "capsule"}:
                line.source_kind = "capsule"
                line.source_id = capsule.id
    assign_plan_line_identity(line)


def create_plan_lines(db: Session, client_id: int, payloads: list) -> list[models.MonthlyPlanLine]:
    created: list[models.MonthlyPlanLine] = []
    for payload in payloads:
        data = _payload_data(payload)
        data.pop("id", None)
        data["plan_id"] = resolve_budget_plan_id(db, client_id, data.get("plan_id"))
        if _active_line_with_identity(db, client_id, data):
            raise ValueError("Monthly plan line already exists for this period and target")
        line = models.MonthlyPlanLine(client_id=client_id)
        db.add(line)
        _apply_plan_line_data(db, client_id, line, data)
        duplicate = _active_duplicate_for_line(db, client_id, line)
        if duplicate:
            db.rollback()
            raise ValueError("Monthly plan line already exists for this period and source")
        created.append(line)
    db.commit()
    for line in created:
        db.refresh(line)
    return created


def update_plan_lines(db: Session, client_id: int, payloads: list) -> list[models.MonthlyPlanLine]:
    saved: list[models.MonthlyPlanLine] = []
    for payload in payloads:
        data = _payload_data(payload)
        line_id = data.pop("id", None)
        if not line_id:
            raise ValueError("Monthly plan line id is required")
        line = db.query(models.MonthlyPlanLine).filter(
            models.MonthlyPlanLine.id == line_id,
            models.MonthlyPlanLine.client_id == client_id,
        ).first()
        if not line:
            raise ValueError("Monthly plan line not found")
        if "plan_id" in data:
            data["plan_id"] = resolve_budget_plan_id(db, client_id, data.get("plan_id"))
        elif line.plan_id is None:
            data["plan_id"] = resolve_budget_plan_id(db, client_id)
        _apply_plan_line_data(db, client_id, line, data)
        duplicate = _active_duplicate_for_line(db, client_id, line)
        if duplicate:
            db.rollback()
            raise ValueError("Monthly plan line already exists for this period and source")
        saved.append(line)
    db.commit()
    for line in saved:
        db.refresh(line)
    return saved


def save_plan_lines(db: Session, client_id: int, payloads: list) -> list[models.MonthlyPlanLine]:
    """Backward-compatible alias for id-required batch updates."""
    return update_plan_lines(db, client_id, payloads)
