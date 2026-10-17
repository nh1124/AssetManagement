"""Reflect the goal scenario into the monthly budget, previewed before it is applied.

Nothing changes until the user confirms the exact preview: apply recomputes it
and refuses when the fingerprint differs, so a budget edit, a new capsule or a
changed goal between the two requests is shown again instead of written blind.

What is written, for each reflected month of the default budget plan:
- one allocation row per near spending event's capsule (split across its funding
  accounts as the capsule's own rows are), funding the shortfall by the target date;
- one allocation row to the chosen savings account for the rest of the monthly
  savings, marked source "goal" so a later reflection finds and replaces it.
Far events stay inside the invested savings, income events are only shown, and
an event's budget reflection (確定 / 条件つき / 試算のみ) decides whether it counts.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from ..domain.errors import Conflict, NotFound, Refused
from ..domain.money import Money
from ..services import capsule_service, ledger_service
from ..services.budget_lines import capsule_shares
from ..services.budget_plan_store import (
    active_lines_for_periods,
    create_plan_lines,
    find_budget_plan_id,
    resolve_budget_plan_id,
    update_plan_lines,
)
from ..services.cache_service import invalidate_client
from ..services.goal_budget_inputs import goal_budget_inputs
from ..services.goal_service import get_life_event
from ..services.life_scenario_scope import lock_client
from ..services.money_storage import money_client_currency

GOAL_SOURCE = "goal"
GOAL_LINE_NAME = "ゴールの積立"


def _periods(start: str, months: int) -> list[str]:
    year, month = (int(part) for part in start.split("-"))
    result = []
    for offset in range(months):
        index = year * 12 + month - 1 + offset
        result.append(f"{index // 12:04d}-{index % 12 + 1:02d}")
    return result


def _major(minor: int, currency: str) -> float:
    return Money(minor, currency).to_float()


def _capsule_rows(lines, period: str, capsule, amount: Money) -> list[tuple]:
    """(account, stored row or None, amount) for each plan row this capsule needs in the month."""
    if capsule is None:
        # Created on apply: no funding plan yet, so one row for the whole amount.
        return [(None, None, amount)]
    stored = [line for line in lines if line.target_period == period and line.line_type == "allocation"
              and line.target_type == "capsule" and line.target_id == capsule.id]
    shares = capsule_shares(capsule, amount)
    by_account = {line.account_id: line for line in stored if line.account_id is not None}
    legacy = next((line for line in stored if line.account_id is None), None)
    if legacy is not None and not by_account:
        # A row predating the funding plan names no account and stands for the whole capsule.
        return [(None, legacy, amount)]
    return [(account_id, by_account.get(account_id) if account_id is not None else legacy, part)
            for account_id, part in shares]


def _plan(db: Session, client_id: int, options: dict, plan_id: int | None) -> dict:
    currency = money_client_currency(db, client_id)
    inputs = goal_budget_inputs(db, client_id, start_period=options["start_period"], near_years=options["near_years"])
    if inputs["scenario"] is None:
        raise Refused("ゴールのシナリオがありません。シナリオ一覧でゴールを選んでください。", status_code=422)
    periods = _periods(options["start_period"], options["months"])
    lines = active_lines_for_periods(db, client_id, plan_id, periods)
    create_for = set(options.get("create_capsules") or [])
    events = inputs["events"]

    required_minor = sum(row["monthly_required_minor"] for row in events
                         if row["direction"] == "expense" and row["status"] == "reflected")
    funded_capsules = []  # (event row, capsule or None, Money)
    for row in events:
        if row["direction"] != "expense" or row["status"] != "reflected" or not row["near"]:
            continue
        if row["capsule_id"] is None and row["event_id"] not in create_for:
            row["status"] = "no_capsule"
            continue
        capsule = capsule_service.get_capsule(db, client_id, row["capsule_id"]) if row["capsule_id"] else None
        row["create_capsule"] = capsule is None
        funded_capsules.append((row, capsule, Money(row["monthly_required_minor"], currency)))

    scenario_minor = Money.from_float(float(inputs["scenario"]["monthly_savings"]), currency).minor
    chosen_minor = scenario_minor if options["savings_source"] == "scenario" else required_minor
    capsule_minor = sum(amount.minor for _, _, amount in funded_capsules)
    account_minor = max(0, chosen_minor - capsule_minor)

    account = None
    if options.get("savings_account_id") is not None:
        account = ledger_service.get_account(db, client_id, options["savings_account_id"])
        if account is None or account.account_type != "asset" or not account.is_active:
            raise NotFound("積立先には有効な資産口座を選んでください。")

    changes = []
    for period in periods:
        for row, capsule, amount in funded_capsules:
            rows = _capsule_rows(lines, period, capsule, amount)
            for account_id, line, part in rows:
                changes.append({
                    "period": period, "kind": "capsule", "event_id": row["event_id"],
                    "capsule_id": capsule.id if capsule else None,
                    "name": capsule.name if capsule else row["name"],
                    "account_id": account_id,
                    "line_id": line.id if line is not None else None,
                    "current_amount": line.amount if line is not None else None,
                    "new_amount": _major(part.minor, currency),
                })
        goal_lines = [line for line in lines if line.target_period == period and line.source_kind == GOAL_SOURCE]
        if account is not None:
            line = next((line for line in goal_lines if line.account_id == account.id), None)
            changes.append({
                "period": period, "kind": "savings", "event_id": None, "capsule_id": None,
                "name": GOAL_LINE_NAME, "account_id": account.id,
                "line_id": line.id if line is not None else None,
                "current_amount": line.amount if line is not None else None,
                "new_amount": _major(account_minor, currency),
            })
            # An earlier reflection to another account is replaced, not added to.
            for old in goal_lines:
                if old.account_id != account.id:
                    changes.append({
                        "period": period, "kind": "retire", "event_id": None, "capsule_id": None,
                        "name": old.name, "account_id": old.account_id, "line_id": old.id,
                        "current_amount": old.amount, "new_amount": 0.0,
                    })
    for change in changes:
        # A missing row that would be written as zero is left missing.
        current = change["current_amount"] if change["current_amount"] is not None else (None if change["new_amount"] else 0.0)
        change["changed"] = change["kind"] == "retire" or current is None or round(current, 6) != round(change["new_amount"], 6)

    previous_account = next((line.account_id for line in lines if line.source_kind == GOAL_SOURCE), None)
    normalized = {
        "savings_source": options["savings_source"], "near_years": options["near_years"],
        "start_period": options["start_period"], "months": options["months"],
        "savings_account_id": options.get("savings_account_id"),
        "create_capsules": sorted(row["event_id"] for row, capsule, _ in funded_capsules if capsule is None),
    }
    fingerprint = hashlib.sha256(json.dumps({"options": normalized, "events": [
        {key: row.get(key) for key in ("event_id", "status", "monthly_required_minor", "capsule_id")} for row in events
    ], "changes": changes}, sort_keys=True, default=str).encode()).hexdigest()
    for row in events:
        row["monthly_required"] = _major(row.pop("monthly_required_minor"), currency)
    return {
        "scenario": inputs["scenario"],
        "options": normalized,
        "periods": periods,
        "savings": {
            "scenario_amount": _major(scenario_minor, currency),
            "required_amount": _major(required_minor, currency),
            "chosen_amount": _major(chosen_minor, currency),
            "capsule_amount": _major(capsule_minor, currency),
            "account_amount": _major(account_minor, currency),
            # Near capsules alone already exceed the monthly savings chosen.
            "shortfall": _major(max(0, capsule_minor - chosen_minor), currency),
            "account_required": account is None and account_minor > 0,
            "suggested_account_id": previous_account,
        },
        "events": events,
        "changes": changes,
        "fingerprint": fingerprint,
        "_funded_capsules": funded_capsules,
    }


def preview(db: Session, client_id: int, options: dict) -> dict:
    """Everything a reflection would do, computed against the plan without writing."""
    result = _plan(db, client_id, options, find_budget_plan_id(db, client_id))
    result.pop("_funded_capsules")
    return result


def apply(db: Session, client_id: int, options: dict, fingerprint: str) -> dict:
    lock_client(db, client_id)
    try:
        planned = _plan(db, client_id, options, find_budget_plan_id(db, client_id))
        if planned["fingerprint"] != fingerprint:
            raise Conflict("ゴールか予算の内容が確認後に変わりました。もう一度確認してください。")
        # Only a confirmed reflection may create the client's first budget plan.
        plan_id = resolve_budget_plan_id(db, client_id)
        currency = money_client_currency(db, client_id)
        created_capsules = {}
        for row, capsule, _ in planned["_funded_capsules"]:
            if capsule is None:
                event = get_life_event(db, client_id, row["event_id"])
                created_capsules[row["event_id"]] = capsule_service.create_capsule_for_goal(db, client_id, event)
        creates, updates = [], []
        for change in planned["changes"]:
            if not change["changed"]:
                continue
            if change["kind"] == "retire":
                updates.append({"id": change["line_id"], "is_active": False})
                continue
            if change["line_id"] is not None:
                updates.append({"id": change["line_id"], "amount": change["new_amount"], "manual_override": False})
                continue
            if change["kind"] == "capsule":
                capsule_id = change["capsule_id"] or created_capsules[change["event_id"]].id
                creates.append({
                    "plan_id": plan_id, "target_period": change["period"], "line_type": "allocation",
                    "target_type": "capsule", "target_id": capsule_id, "account_id": change["account_id"],
                    "amount": change["new_amount"], "source": "capsule", "source_kind": "capsule",
                    "cash_treatment": "auto",
                })
            else:
                creates.append({
                    "plan_id": plan_id, "target_period": change["period"], "line_type": "allocation",
                    "target_type": "account", "account_id": change["account_id"], "name": change["name"],
                    "amount": change["new_amount"], "source": GOAL_SOURCE, "source_kind": GOAL_SOURCE,
                    "cash_treatment": "auto",
                })
        try:
            if updates:
                update_plan_lines(db, client_id, updates, commit=False)
            if creates:
                create_plan_lines(db, client_id, creates, commit=False)
        except ValueError as exc:
            raise Conflict(f"予算行を書き込めませんでした：{exc}") from exc
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return {
        "applied": len(creates) + len(updates),
        "created_capsules": [{"event_id": event_id, "capsule_id": capsule.id, "name": capsule.name}
                             for event_id, capsule in created_capsules.items()],
        "periods": planned["periods"],
        "currency": currency,
    }
