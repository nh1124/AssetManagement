"""Plan-line vocabulary: what a line means, and how its amount moves money.

Every function here answers a question about a single plan line or a bucket of
them without touching the database. A plan line reaches these helpers either
as a MonthlyPlanLine row or as the dict a suggestion is built as, which is why
reads go through _line_attr instead of attribute access.
"""
from __future__ import annotations

from datetime import datetime
import json
from typing import Iterable

from .. import models
from ..domain.money import Money


INFLOW_LINE_TYPES = {"income", "borrowing", "drawdown"}
OUTFLOW_LINE_TYPES = {"expense", "allocation", "debt_payment"}
NON_CASH_TRANSACTION_TYPES = {"CreditExpense", "CreditAssetPurchase"}
ASSET_FLOW_BUCKETS = ("asset",)


def _capsule_allocation_amounts(capsule: models.Capsule, currency: str) -> list[tuple[int | None, Money]]:
    """The monthly contribution shares in the funding plan's stable order."""
    return capsule_shares(capsule, Money(capsule.monthly_contribution_minor or 0, currency))


def capsule_shares(capsule: models.Capsule, whole: Money) -> list[tuple[int | None, Money]]:
    """Split a monthly amount across the capsule's funding accounts, as its plan rows do."""
    sources = sorted(capsule.funding_sources, key=lambda source: (source.sort_order, source.id))
    if not sources:
        return [(None, whole)]
    weights = [source.target_amount_minor for source in sources]
    # A zero-target plan has no relative weights; retain its rows and the whole
    # contribution with equal shares, including the one-source legacy shape.
    parts = whole.allocate(weights if any(weights) else [1] * len(sources))
    return [(source.account_id, part) for source, part in zip(sources, parts)]


def _line_display_name(line: models.MonthlyPlanLine, name_maps: dict[str, dict[int, str]]) -> str:
    if line.name:
        return line.name
    if line.target_type == "account" and line.account_id:
        return name_maps["account"].get(line.account_id, "Account")
    if line.target_id:
        return name_maps.get(line.target_type, {}).get(line.target_id, line.target_type.title())
    return line.line_type.replace("_", " ").title()


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
    if source and source != "manual":
        if source == "recurrence":
            return "recurring"
        return source
    target_type = _line_attr(line, "target_type")
    if target_type in {"capsule", "product"} and _line_attr(line, "target_id"):
        return target_type
    return "manual"


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


def line_identity_key(line: models.MonthlyPlanLine | dict) -> tuple:
    getter = line.get if isinstance(line, dict) else lambda key, default=None: getattr(line, key, default)
    account_id = getter("account_id")
    target_id = getter("target_id")
    name = "" if account_id or target_id else (getter("name") or "").strip().lower()
    source_kind = _line_source_kind(line)
    return (
        getter("plan_id") or 0,
        getter("target_period"),
        source_kind,
        getter("line_type"),
        getter("target_type") or "manual",
        account_id or 0,
        getter("source_account_id") or 0,
        target_id or 0,
        name,
        getter("cash_treatment", "auto") or "auto",
    )


def plan_line_identity_key(line: models.MonthlyPlanLine | dict) -> str:
    return json.dumps(line_identity_key(line), ensure_ascii=True, separators=(",", ":"))


def assign_plan_line_identity(line: models.MonthlyPlanLine) -> None:
    line.source_kind = _line_source_kind(line)
    line.identity_key = plan_line_identity_key(line)


def newest_line_key(line: models.MonthlyPlanLine) -> tuple:
    return (
        line.updated_at or line.created_at or datetime.min,
        line.created_at or datetime.min,
        line.id or 0,
    )


def account_flow_bucket(account: models.Account | None) -> str:
    if not account:
        return "unknown"
    if account.account_type in {"asset", "liability", "income", "expense"}:
        return account.account_type
    return "unknown"


def _empty_flow() -> dict[str, float]:
    return {
        "inflow": 0.0,
        "expense": 0.0,
        "allocation": 0.0,
        "debt": 0.0,
        "asset": 0.0,
        "financing": 0.0,
        "internal_transfer": 0.0,
        "non_cash_budget": 0.0,
    }


def _empty_balance() -> dict[str, float]:
    return {
        "asset": 0.0,
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

    if from_bucket == "asset" and to_bucket == "expense":
        flow["expense"] += amount
    elif from_bucket == "asset" and to_bucket == "liability":
        flow["debt"] += amount
        flow["financing"] -= amount
    elif from_bucket == "liability" and to_bucket in ASSET_FLOW_BUCKETS:
        flow["inflow"] += amount
        flow["financing"] += amount
    elif from_bucket == "income" and to_bucket in ASSET_FLOW_BUCKETS:
        flow["inflow"] += amount
    elif from_bucket == "asset" and to_bucket == "asset":
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
        flow["asset"] = amount
        if line_type == "borrowing":
            flow["financing"] = amount
    elif line_type == "expense":
        flow["expense"] = amount
        flow["asset"] = -amount
    elif line_type == "allocation":
        flow["allocation"] = amount
        flow["asset"] = -amount
    elif line_type == "debt_payment":
        flow["debt"] = amount
        flow["asset"] = -amount
        flow["financing"] = -amount
    return flow


def _sum_lines(lines: Iterable[dict], *line_types: str) -> float:
    wanted = set(line_types)
    return sum((line.get("amount") or 0.0) for line in lines if line.get("line_type") in wanted)


def _sum_actual(lines: Iterable[dict], *line_types: str) -> float:
    wanted = set(line_types)
    return sum((line.get("actual") or 0.0) for line in lines if line.get("line_type") in wanted)
