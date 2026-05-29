from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from .accounting_service import calculate_account_journal_balance
from .budget_plan_service import assign_plan_line_identity, _line_identity_key, _newest_line_key, get_or_create_default_plan, period_to_range
from .cache_service import invalidate_client
from .registry_service import ensure_registry_entries, registry_entry_amount_for_period, registry_target_account_id


PLAN_SOURCE_LINE_TYPES = {"expense", "allocation", "debt_payment", "borrowing", "drawdown"}


@dataclass
class SourceCandidate:
    source_account_id: int
    amount: float
    reason: str
    evidence: str


def _account_names(db: Session, client_id: int) -> dict[int, str]:
    return {
        account.id: account.name
        for account in db.query(models.Account)
        .filter(models.Account.client_id == client_id)
        .all()
    }


def _account_name(names: dict[int, str], account_id: int | None) -> str | None:
    if not account_id:
        return None
    return names.get(account_id) or f"id={account_id}"


def _line_source_from_transaction(line: models.MonthlyPlanLine, tx: models.Transaction) -> int | None:
    if line.line_type == "expense":
        if tx.type in {"Expense", "CreditExpense"} and tx.to_account_id == line.account_id:
            return tx.from_account_id
        return None
    if line.line_type == "allocation":
        if tx.type in {"Transfer", "CreditAssetPurchase"} and tx.to_account_id == line.account_id:
            return tx.from_account_id
        return None
    if line.line_type == "debt_payment":
        if tx.type == "LiabilityPayment" and tx.to_account_id == line.account_id:
            return tx.from_account_id
        return None
    if line.line_type == "borrowing":
        if tx.type == "Borrowing" and tx.from_account_id == line.account_id:
            return tx.to_account_id
        return None
    if line.line_type == "drawdown":
        if tx.type == "Transfer" and tx.from_account_id == line.account_id:
            return tx.to_account_id
        return None
    return None


def _infer_source_from_recurring(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    if not line.recurring_transaction_id:
        return None
    recurring = (
        db.query(models.RecurringTransaction)
        .filter(
            models.RecurringTransaction.id == line.recurring_transaction_id,
            models.RecurringTransaction.client_id == line.client_id,
        )
        .first()
    )
    if not recurring or not recurring.from_account_id:
        return None
    return SourceCandidate(
        source_account_id=recurring.from_account_id,
        amount=float(recurring.amount or 0.0),
        reason="recurring",
        evidence=f"recurring_id={recurring.id}",
    )


def _infer_source_from_registry(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    if not line.account_id:
        return None
    period_start, _ = period_to_range(line.target_period)
    entries = (
        db.query(models.RegistryEntry)
        .filter(
            models.RegistryEntry.client_id == line.client_id,
            models.RegistryEntry.is_active.is_(True),
            models.RegistryEntry.budget_active.is_(True),
            models.RegistryEntry.line_type == line.line_type,
            models.RegistryEntry.source_account_id.isnot(None),
        )
        .all()
    )

    grouped: dict[int, dict[str, Any]] = defaultdict(lambda: {"amount": 0.0, "ids": []})
    for entry in entries:
        if registry_target_account_id(entry) != line.account_id:
            continue
        amount = registry_entry_amount_for_period(db, entry, line.target_period, period_start, line.client_id)
        if amount <= 0:
            continue
        group = grouped[entry.source_account_id]
        group["amount"] = float(group["amount"]) + float(amount)
        group["ids"].append(entry.id)

    if len(grouped) != 1:
        return None
    source_account_id, data = next(iter(grouped.items()))
    return SourceCandidate(
        source_account_id=source_account_id,
        amount=float(data["amount"]),
        reason="registry",
        evidence="registry_entry_ids=" + ",".join(str(item) for item in data["ids"]),
    )


def _infer_source_from_transactions(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    period_start, period_end = period_to_range(line.target_period)
    txs = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.client_id == line.client_id,
            models.Transaction.date >= period_start,
            models.Transaction.date < period_end,
        )
        .all()
    )

    grouped: dict[int, dict[str, Any]] = defaultdict(lambda: {"amount": 0.0, "ids": []})
    for tx in txs:
        source_account_id = _line_source_from_transaction(line, tx)
        if not source_account_id:
            continue
        group = grouped[source_account_id]
        group["amount"] = float(group["amount"]) + float(tx.amount or 0.0)
        group["ids"].append(tx.id)

    if len(grouped) != 1:
        return None
    source_account_id, data = next(iter(grouped.items()))
    return SourceCandidate(
        source_account_id=source_account_id,
        amount=float(data["amount"]),
        reason="transactions",
        evidence="transaction_ids=" + ",".join(str(item) for item in data["ids"]),
    )


def infer_plan_line_source(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    return (
        _infer_source_from_recurring(db, line)
        or _infer_source_from_registry(db, line)
        or _infer_source_from_transactions(db, line)
    )


def _missing_source_items(db: Session, client_id: int) -> list[dict[str, Any]]:
    names = _account_names(db, client_id)
    lines = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.is_active.is_(True),
            models.MonthlyPlanLine.source_account_id.is_(None),
            models.MonthlyPlanLine.line_type.in_(PLAN_SOURCE_LINE_TYPES),
        )
        .order_by(models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id)
        .all()
    )

    items: list[dict[str, Any]] = []
    for line in lines:
        candidate = infer_plan_line_source(db, line)
        items.append(
            {
                "line_id": line.id,
                "period": line.target_period,
                "line_type": line.line_type,
                "name": line.name,
                "target_account": _account_name(names, line.account_id),
                "amount": line.amount,
                "repairable": candidate is not None,
                "suggested_source_account_id": candidate.source_account_id if candidate else None,
                "suggested_source_account": _account_name(names, candidate.source_account_id) if candidate else None,
                "reason": candidate.reason if candidate else "no_single_source",
                "evidence": candidate.evidence if candidate else None,
            }
        )
    return items


def _balance_drift_items(db: Session, client_id: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    accounts = (
        db.query(models.Account)
        .filter(models.Account.client_id == client_id)
        .order_by(models.Account.account_type, models.Account.name)
        .all()
    )
    for account in accounts:
        journal_balance = round(calculate_account_journal_balance(db, account), 2)
        stored_balance = round(float(account.balance or 0.0), 2)
        diff = round(journal_balance - stored_balance, 2)
        if abs(diff) >= 1:
            items.append(
                {
                    "account_id": account.id,
                    "account": account.name,
                    "account_type": account.account_type,
                    "stored_balance": stored_balance,
                    "journal_balance": journal_balance,
                    "diff": diff,
                    "repairable": True,
                }
            )
    return items


def _registry_recurring_items(db: Session, client_id: int) -> list[dict[str, Any]]:
    names = _account_names(db, client_id)
    entries = (
        db.query(models.RegistryEntry)
        .filter(
            models.RegistryEntry.client_id == client_id,
            models.RegistryEntry.is_active.is_(True),
            models.RegistryEntry.source_recurring_transaction_id.isnot(None),
        )
        .order_by(models.RegistryEntry.id)
        .all()
    )
    items: list[dict[str, Any]] = []
    for entry in entries:
        recurring = (
            db.query(models.RecurringTransaction)
            .filter(
                models.RecurringTransaction.id == entry.source_recurring_transaction_id,
                models.RecurringTransaction.client_id == client_id,
            )
            .first()
        )
        if not recurring:
            items.append(
                {
                    "registry_entry_id": entry.id,
                    "name": entry.name,
                    "problem": "missing_recurring",
                    "repairable": False,
                }
            )
            continue
        expected_target = recurring.to_account_id if entry.line_type in {"expense", "debt_payment"} else None
        mismatch = (
            entry.source_account_id != recurring.from_account_id
            or entry.destination_account_id != recurring.to_account_id
            or (expected_target is not None and entry.budget_account_id != expected_target)
        )
        if mismatch:
            items.append(
                {
                    "registry_entry_id": entry.id,
                    "name": entry.name,
                    "problem": "account_mismatch",
                    "source_account": _account_name(names, entry.source_account_id),
                    "expected_source_account": _account_name(names, recurring.from_account_id),
                    "destination_account": _account_name(names, entry.destination_account_id),
                    "expected_destination_account": _account_name(names, recurring.to_account_id),
                    "repairable": True,
                }
            )
    return items


def _duplicate_plan_line_items(db: Session, client_id: int) -> list[dict[str, Any]]:
    grouped: dict[tuple, list[models.MonthlyPlanLine]] = defaultdict(list)
    for line in (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.is_active.is_(True),
        )
        .all()
    ):
        grouped[_line_identity_key(line)].append(line)

    items = []
    for lines in grouped.values():
        if len(lines) <= 1:
            continue
        keeper = max(lines, key=_newest_line_key)
        items.append(
            {
                "problem": "duplicate_active_plan_lines",
                "period": keeper.target_period,
                "plan_id": keeper.plan_id,
                "line_type": keeper.line_type,
                "account_id": keeper.account_id,
                "name": keeper.name,
                "keeper_line_id": keeper.id,
                "duplicate_line_ids": [line.id for line in lines if line.id != keeper.id],
                "repairable": True,
            }
        )
    return items


def check_data_health(db: Session, client_id: int) -> dict[str, Any]:
    default_plan = db.query(models.BudgetPlan).filter_by(client_id=client_id, is_default=True).first()
    null_plan_count = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.is_active.is_(True),
            models.MonthlyPlanLine.plan_id.is_(None),
        )
        .count()
    )
    missing_source = _missing_source_items(db, client_id)
    balance_drift = _balance_drift_items(db, client_id)
    registry_recurring = _registry_recurring_items(db, client_id)
    duplicate_plan_lines = _duplicate_plan_line_items(db, client_id)

    issues = [
        {
            "code": "budget_plan_defaults",
            "severity": "warning",
            "title": "Default budget plan links",
            "detail": "Active plan lines should be attached to the default Budget Plan.",
            "count": (0 if default_plan else 1) + null_plan_count,
            "repairable": True,
            "items": [
                {"problem": "missing_default_plan", "repairable": True}
                for _ in ([] if default_plan else [1])
            ]
            + [
                {"problem": "active_line_without_plan", "count": null_plan_count, "repairable": True}
                for _ in ([] if null_plan_count == 0 else [1])
            ],
        },
        {
            "code": "plan_line_sources",
            "severity": "warning",
            "title": "Plan line source accounts",
            "detail": "Cash Flow accuracy depends on knowing whether each plan line moves cash, debt, or another asset role.",
            "count": len(missing_source),
            "repairable": any(item["repairable"] for item in missing_source),
            "items": missing_source[:100],
        },
        {
            "code": "account_balances",
            "severity": "error",
            "title": "Account balance drift",
            "detail": "Stored account balances should match posted journal entries.",
            "count": len(balance_drift),
            "repairable": bool(balance_drift),
            "items": balance_drift[:100],
        },
        {
            "code": "registry_recurring_links",
            "severity": "warning",
            "title": "Registry and recurrence links",
            "detail": "Registry entries linked to recurring transactions should share the same account flow.",
            "count": len(registry_recurring),
            "repairable": any(item["repairable"] for item in registry_recurring),
            "items": registry_recurring[:100],
        },
        {
            "code": "duplicate_plan_lines",
            "severity": "warning",
            "title": "Duplicate active plan lines",
            "detail": "Only one active plan line should exist for the same period, source, and target.",
            "count": len(duplicate_plan_lines),
            "repairable": bool(duplicate_plan_lines),
            "items": duplicate_plan_lines[:100],
        },
    ]
    total = sum(issue["count"] for issue in issues)
    repairable = sum(1 for issue in issues if issue["repairable"] and issue["count"] > 0)
    return {
        "status": "ok" if total == 0 else "issues_found",
        "total_issues": total,
        "repairable_groups": repairable,
        "issues": issues,
    }


def repair_data_health(db: Session, client_id: int) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []

    missing_default = db.query(models.BudgetPlan.id).filter_by(client_id=client_id, is_default=True).first() is None
    pre_null_plan_count = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.is_active.is_(True),
            models.MonthlyPlanLine.plan_id.is_(None),
        )
        .count()
    )
    plan = get_or_create_default_plan(db, client_id)
    null_plan_count = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.is_active.is_(True),
            models.MonthlyPlanLine.plan_id.is_(None),
        )
        .update({"plan_id": plan.id}, synchronize_session=False)
    )
    actions.append({"code": "budget_plan_defaults", "updated": pre_null_plan_count + null_plan_count + (1 if missing_default else 0)})

    before_registry_count = (
        db.query(models.RegistryEntry)
        .filter(models.RegistryEntry.client_id == client_id)
        .count()
    )
    ensure_registry_entries(db, client_id)
    after_registry_count = (
        db.query(models.RegistryEntry)
        .filter(models.RegistryEntry.client_id == client_id)
        .count()
    )
    actions.append({"code": "registry_entries", "updated": max(0, after_registry_count - before_registry_count)})

    source_updates = 0
    identity_updates = 0
    plan_lines = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.is_active.is_(True),
        )
        .all()
    )
    for line in plan_lines:
        before_identity = line.identity_key
        if line.source_account_id is None and line.line_type in PLAN_SOURCE_LINE_TYPES:
            candidate = infer_plan_line_source(db, line)
            if candidate:
                line.source_account_id = candidate.source_account_id
                source_updates += 1
        assign_plan_line_identity(line)
        if line.identity_key != before_identity:
            identity_updates += 1
    actions.append({"code": "plan_line_sources", "updated": source_updates})
    actions.append({"code": "plan_line_identities", "updated": identity_updates})

    balance_updates = 0
    for account in db.query(models.Account).filter(models.Account.client_id == client_id).all():
        journal_balance = round(calculate_account_journal_balance(db, account), 2)
        stored_balance = round(float(account.balance or 0.0), 2)
        if abs(journal_balance - stored_balance) >= 1:
            account.balance = journal_balance
            balance_updates += 1
    actions.append({"code": "account_balances", "updated": balance_updates})

    registry_updates = 0
    entries = (
        db.query(models.RegistryEntry)
        .filter(
            models.RegistryEntry.client_id == client_id,
            models.RegistryEntry.is_active.is_(True),
            models.RegistryEntry.source_recurring_transaction_id.isnot(None),
        )
        .all()
    )
    for entry in entries:
        recurring = (
            db.query(models.RecurringTransaction)
            .filter(
                models.RecurringTransaction.id == entry.source_recurring_transaction_id,
                models.RecurringTransaction.client_id == client_id,
            )
            .first()
        )
        if not recurring:
            continue
        changed = False
        if entry.source_account_id != recurring.from_account_id:
            entry.source_account_id = recurring.from_account_id
            changed = True
        if entry.destination_account_id != recurring.to_account_id:
            entry.destination_account_id = recurring.to_account_id
            changed = True
        if entry.line_type in {"expense", "debt_payment"} and entry.budget_account_id != recurring.to_account_id:
            entry.budget_account_id = recurring.to_account_id
            changed = True
        if changed:
            registry_updates += 1
    actions.append({"code": "registry_recurring_links", "updated": registry_updates})

    duplicate_updates = 0
    grouped: dict[tuple, list[models.MonthlyPlanLine]] = defaultdict(list)
    for line in (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.is_active.is_(True),
        )
        .all()
    ):
        grouped[_line_identity_key(line)].append(line)
    for lines in grouped.values():
        if len(lines) <= 1:
            continue
        keeper = max(lines, key=_newest_line_key)
        for duplicate in lines:
            if duplicate.id != keeper.id:
                duplicate.is_active = False
                duplicate_updates += 1
    actions.append({"code": "duplicate_plan_lines", "updated": duplicate_updates})

    db.commit()
    invalidate_client(client_id)
    return {
        "status": "repaired",
        "actions": actions,
        "health": check_data_health(db, client_id),
    }
