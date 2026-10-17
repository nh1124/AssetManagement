"""Reflect the goal scenario into the monthly budget, previewed before it is applied.

Nothing changes until the user confirms the exact preview: apply recomputes it
and refuses when the fingerprint differs, so a budget edit, a new capsule or a
changed goal between the two requests is shown again instead of written blind.

The scenario's monthly savings is the one total; the reflection divides it:
- savings already in the budget come first -- allocation definitions (収支・配分の
  定義) into asset accounts, hand-entered allocations into asset accounts, and the
  monthly amounts of capsules the goal does not fund. The user may leave any of
  them out, so a transfer that is not really saving does not shrink the goal;
- one allocation row per near spending event's capsule (split across its funding
  accounts as the capsule's own rows are), funding the shortfall by the target date;
- the rest goes either to one allocation row for the chosen savings account,
  marked source "goal" so a later reflection finds and replaces it, or into the
  amount of one monthly allocation definition, which then carries it every month
  (and into the transactions it generates).
Counting existing savings is what keeps the same money from being planned twice.
Far events stay inside the invested savings, income events are only shown, and
an event's budget reflection (確定 / 条件つき / 試算のみ) decides whether it counts.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy.orm import Session

from ..domain.errors import Conflict, NotFound, Refused
from ..domain.money import Money
from ..services import capsule_service, ledger_service, registry_service
from ..services.budget_lines import capsule_shares
from ..services.budget_plan_store import (
    active_lines_for_periods,
    create_plan_lines,
    find_budget_plan_id,
    resolve_budget_plan_id,
    update_plan_lines,
)
from ..services.cache_service import invalidate_client
from ..services import goal_baseline_service, goal_budget_record, life_scenario_service
from ..services.budget_plan_service import get_budget_summary
from ..services.goal_service import list_goals
from ..services.life_scenario_scope import get_goal
from ..services.strategy_service import DEFAULT_NEAR_YEARS, event_monthly_allocation
from ..services.goal_budget_inputs import goal_budget_inputs
from ..services.goal_service import get_life_event
from ..services.life_scenario_scope import lock_client
from ..services.money_storage import money_client_currency

GOAL_SOURCE = "goal"
GOAL_LINE_NAME = "ゴールの積立"
PRIORITY_WEIGHTS = {1: 3, 2: 2, 3: 1}


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


def _existing_savings(db: Session, client_id: int, periods: list[str], lines, skip_capsules: set[int], currency: str) -> list[dict]:
    """Savings the budget already plans in these months, outside what this reflection writes."""
    rows = []
    for entry in registry_service.list_entries(db, client_id):
        if entry.line_type != "allocation" or not entry.is_active or not entry.budget_active:
            continue
        account_id = registry_service.registry_target_account_id(entry)
        account = ledger_service.get_account(db, client_id, account_id) if account_id else None
        if account is None or account.account_type != "asset":
            continue
        amounts = {}
        for period in periods:
            year, month = (int(part) for part in period.split("-"))
            amount = registry_service.registry_entry_amount_for_period(db, entry, period, date(year, month, 1), client_id)
            amounts[period] = Money.from_float(float(amount), currency).minor
        if not any(amounts.values()):
            continue
        rows.append({"key": f"definition:{entry.id}", "kind": "definition", "id": entry.id, "name": entry.name,
                     "account_id": account_id, "amounts": amounts,
                     # Only a plain monthly amount in the client currency can be set from the goal.
                     "updatable": (entry.frequency or "Monthly") == "Monthly" and entry.currency == currency,
                     "current_amount": entry.amount})
    manual: dict[str, dict] = {}
    for line in lines:
        if (line.line_type == "allocation" and line.target_type == "account" and line.account_id
                and line.source_kind == "manual"):
            key = f"manual:{line.account_id}:{(line.name or '').strip()}"
            row = manual.setdefault(key, {"key": key, "kind": "manual", "id": None, "name": line.name or "",
                                          "account_id": line.account_id, "amounts": dict.fromkeys(periods, 0),
                                          "updatable": False, "current_amount": None})
            row["amounts"][line.target_period] += line.amount_minor or 0
    rows.extend(manual.values())
    for capsule in capsule_service.list_capsules(db, client_id, limit=10000):
        if capsule.id in skip_capsules:
            continue
        amounts = {}
        for period in periods:
            stored = [line for line in lines if line.target_period == period and line.line_type == "allocation"
                      and line.target_type == "capsule" and line.target_id == capsule.id]
            # Stored rows are the month's plan; without them the budget shows the capsule's own amount.
            amounts[period] = sum(line.amount_minor or 0 for line in stored) if stored else (capsule.monthly_contribution_minor or 0)
        if not any(amounts.values()):
            continue
        rows.append({"key": f"capsule:{capsule.id}", "kind": "capsule", "id": capsule.id, "name": capsule.name,
                     "account_id": None, "amounts": amounts, "updatable": False, "current_amount": None})
    return rows


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

    account = None
    if options.get("savings_account_id") is not None:
        if options.get("savings_definition_id") is not None:
            raise Refused("積立先は口座か定義のどちらか一方を選んでください。", status_code=422)
        account = ledger_service.get_account(db, client_id, options["savings_account_id"])
        if account is None or account.account_type != "asset" or not account.is_active:
            raise NotFound("積立先には有効な資産口座を選んでください。")

    funded_ids = {capsule.id for _, capsule, _ in funded_capsules if capsule is not None}
    existing = _existing_savings(db, client_id, periods, lines, funded_ids, currency)
    definition = None
    if options.get("savings_definition_id") is not None:
        definition = next((row for row in existing if row["kind"] == "definition"
                           and row["id"] == options["savings_definition_id"]), None)
        if definition is None or not definition["updatable"]:
            raise NotFound("積立先の定義は、資産口座への毎月の配分の定義から選んでください。")
    uncounted = set(options.get("uncounted") or [])
    for row in existing:
        row["destination"] = row is definition
        # The destination definition is rewritten below, so it is not also counted.
        row["counted"] = row["key"] not in uncounted and not row["destination"]
    counted = {period: sum(row["amounts"][period] for row in existing if row["counted"]) for period in periods}
    residual = {period: max(0, chosen_minor - capsule_minor - counted[period]) for period in periods}
    account_minor = residual[periods[0]]
    # How each event is funded each month, as event progress will read it: a near
    # event by its capsule, a far one by its priority share of everything else
    # saved (existing savings and the goal row alike).
    funded_events = {row["event_id"] for row, _, _ in funded_capsules}
    far = [row for row in events if row["direction"] == "expense" and row["status"] == "reflected" and not row["near"]]
    far_pool = max(0, chosen_minor - capsule_minor)
    weights = [PRIORITY_WEIGHTS.get(row["priority"], 1) for row in far]
    shares = Money(far_pool, currency).allocate(weights) if far and sum(weights) else []
    far_share = {row["event_id"]: share.minor for row, share in zip(far, shares)}
    for row in events:
        if row["event_id"] in funded_events:
            row["allocation_minor"] = row["monthly_required_minor"]
        else:
            row["allocation_minor"] = far_share.get(row["event_id"], 0)

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
        if definition is not None:
            # The definition now carries the goal savings; an earlier goal row would double it.
            for old in goal_lines:
                changes.append({
                    "period": period, "kind": "retire", "event_id": None, "capsule_id": None,
                    "name": old.name, "account_id": old.account_id, "line_id": old.id,
                    "current_amount": old.amount, "new_amount": 0.0,
                })
        if account is not None:
            line = next((line for line in goal_lines if line.account_id == account.id), None)
            changes.append({
                "period": period, "kind": "savings", "event_id": None, "capsule_id": None,
                "name": GOAL_LINE_NAME, "account_id": account.id,
                "line_id": line.id if line is not None else None,
                "current_amount": line.amount if line is not None else None,
                "new_amount": _major(residual[period], currency),
            })
            # An earlier reflection to another account is replaced, not added to.
            for old in goal_lines:
                if old.account_id != account.id:
                    changes.append({
                        "period": period, "kind": "retire", "event_id": None, "capsule_id": None,
                        "name": old.name, "account_id": old.account_id, "line_id": old.id,
                        "current_amount": old.amount, "new_amount": 0.0,
                    })
    if definition is not None:
        changes.append({
            "period": periods[0], "kind": "definition", "event_id": None, "capsule_id": None,
            "definition_id": definition["id"], "name": definition["name"], "account_id": definition["account_id"],
            "line_id": None, "current_amount": definition["current_amount"],
            "new_amount": _major(residual[periods[0]], currency),
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
        "savings_definition_id": options.get("savings_definition_id"),
        "uncounted": sorted(uncounted),
        "create_capsules": sorted(row["event_id"] for row, capsule, _ in funded_capsules if capsule is None),
    }
    fingerprint = hashlib.sha256(json.dumps({"options": normalized, "events": [
        {key: row.get(key) for key in ("event_id", "status", "monthly_required_minor", "capsule_id")} for row in events
    ], "existing": existing, "changes": changes}, sort_keys=True, default=str).encode()).hexdigest()
    start = periods[0]
    existing_out = [{**{key: row[key] for key in ("key", "kind", "id", "name", "account_id", "updatable", "counted", "destination")},
                     "amount": _major(row["amounts"][start], currency)} for row in existing]
    for row in events:
        row["monthly_required"] = _major(row.pop("monthly_required_minor"), currency)
        row["allocation"] = _major(row.pop("allocation_minor"), currency)
    return {
        "scenario": inputs["scenario"],
        "options": normalized,
        "periods": periods,
        "savings": {
            "scenario_amount": _major(scenario_minor, currency),
            "required_amount": _major(required_minor, currency),
            "chosen_amount": _major(chosen_minor, currency),
            "existing_amount": _major(counted[start], currency),
            "capsule_amount": _major(capsule_minor, currency),
            "account_amount": _major(account_minor, currency),
            # Existing savings and near capsules already exceed the monthly savings chosen.
            "shortfall": _major(max(0, capsule_minor + counted[start] - chosen_minor), currency),
            "account_required": account is None and definition is None and account_minor > 0,
            "suggested_account_id": previous_account,
        },
        "events": events,
        "existing": existing_out,
        "changes": changes,
        "fingerprint": fingerprint,
        "_funded_capsules": funded_capsules,
    }


def preview(db: Session, client_id: int, options: dict) -> dict:
    """Everything a reflection would do, computed against the plan without writing."""
    result = _plan(db, client_id, options, find_budget_plan_id(db, client_id))
    result.pop("_funded_capsules")
    return result


def apply(db: Session, client_id: int, options: dict, fingerprint: str, *, update_baseline: bool = False) -> dict:
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
        creates, updates, definitions = [], [], []
        for change in planned["changes"]:
            if not change["changed"]:
                continue
            if change["kind"] == "definition":
                definitions.append(change)
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
            for change in definitions:
                registry_service.update_entry(db, client_id, change["definition_id"], {"amount": change["new_amount"]}, commit=False)
            goal_budget_record.record(
                db, client_id, scenario_id=planned["scenario"]["id"], start_period=planned["periods"][0],
                end_period=planned["periods"][-1], options=planned["options"], summary=planned["savings"],
                events=[{key: row.get(key) for key in (
                    "event_id", "lineage", "name", "direction", "status", "near", "monthly_required", "allocation",
                    "target_amount", "target_date",
                )} for row in planned["events"]],
            )
            if update_baseline:
                # Q4: the user may move the baseline to the plan the budget now follows.
                goal_baseline_service.capture(db, client_id, "reflection")
        except ValueError as exc:
            raise Conflict(f"予算行を書き込めませんでした：{exc}") from exc
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return {
        "applied": len(creates) + len(updates) + len(definitions),
        "baseline_updated": update_baseline,
        "created_capsules": [{"event_id": event_id, "capsule_id": capsule.id, "name": capsule.name}
                             for event_id, capsule in created_capsules.items()],
        "periods": planned["periods"],
        "currency": currency,
    }


def _months_between(start: str, end: str) -> int:
    (start_year, start_month), (end_year, end_month) = ((int(part) for part in value.split("-")) for value in (start, end))
    return (end_year - start_year) * 12 + (end_month - start_month)


def _planned_far_savings(records, lineage: str, period: str) -> float:
    """What the reflections so far set aside each month for an event while it was far."""
    total = 0.0
    for row in records:
        entry = next((item for item in row.events or [] if item.get("lineage") == lineage), None)
        if entry is None or entry.get("near") or entry.get("status") != "reflected":
            continue
        last = min(row.end_period, period)
        months = _months_between(row.start_period, last) + 1
        if months > 0:
            total += float(entry.get("allocation") or 0.0) * months
    return total


def _reminders(goal, total: float, events, records, period: str, budget_total: float) -> list[dict]:
    """Why the budget may no longer follow the goal: each a reason to reflect again."""
    record = records[-1] if records else None
    if record is None:
        return [{"code": "never", "message": "ゴールをまだ予算に反映していません。"}]
    reminders = []
    if record.scenario_id != goal.id:
        reminders.append({"code": "goal_changed", "message": "ゴールのシナリオが前回の反映から変わっています。"})
    if record.end_period < period:
        reminders.append({"code": "coverage_ended", "message": f"予算に反映したのは {record.end_period} までです。{period} 以降の予算を更新してください。"})
    elif record.end_period == period:
        reminders.append({"code": "coverage_ending", "message": f"予算に反映したのは今月（{period}）までです。来月分の更新が必要です。"})
    options = record.options or {}
    summary = record.summary or {}
    if options.get("savings_source") == "scenario" and abs(float(summary.get("scenario_amount") or 0) - total) >= 1:
        reminders.append({"code": "savings_changed",
                          "message": f"月の積立が前回の反映（{float(summary.get('scenario_amount') or 0):,.0f}）から {total:,.0f} に変わっています。"})
    if record.scenario_id == goal.id:
        known = {row.get("lineage"): row for row in record.events or []}
        near_years = options.get("near_years", DEFAULT_NEAR_YEARS)
        changed = False
        for event in events:
            if event.direction != "expense":
                continue
            row = known.get(event.lineage)
            if row is None:
                changed = True
                continue
            if ("target_amount" in row and abs(float(row["target_amount"] or 0) - float(event.target_amount or 0)) >= 1) or (
                    "target_date" in row and row["target_date"] != event.target_date.isoformat()):
                changed = True
            months = _months_between(period, event.target_date.strftime("%Y-%m"))
            if row.get("status") == "reflected" and not row.get("near") and near_years is not None and months < near_years * 12:
                handover = _planned_far_savings(records, event.lineage, period)
                reminders.append({
                    "code": "event_near", "event_id": event.id,
                    "message": f"「{event.name}」が取り置きで積み立てる範囲に入りました。取り置きの月額を予算に入れてください。"
                               + (f"これまで積立に含めて計画した約 {handover:,.0f} を取り置きへ確保すると、月額を抑えられます。" if handover >= 1 else ""),
                    "handover_amount": round(handover, 2),
                })
        if changed or {row.get("lineage") for row in record.events or [] if row.get("direction") == "expense"} - {event.lineage for event in events}:
            reminders.append({"code": "events_changed", "message": "ライフイベントが前回の反映から追加・変更されています。"})
    if abs(budget_total - total) >= max(1.0, total * 0.01):
        reminders.append({"code": "budget_drift",
                          "message": f"今月の予算の積立の合計（{budget_total:,.0f}）が月の積立（{total:,.0f}）と {budget_total - total:+,.0f} ずれています。"})
    return reminders


def status(db: Session, client_id: int, period: str) -> dict:
    """How the monthly savings is divided among the goal's events, and whether to reflect again.

    Read-only. The budget side counts this month's allocations into capsules and
    asset accounts -- everything the budget sets aside, whatever its source.
    """
    goal = get_goal(db, client_id)
    if goal is None:
        return {"goal": None, "events": [], "budget": None, "reflection": None, "reminders": []}
    total = life_scenario_service.monthly_savings(db, goal)
    year, month = (int(part) for part in period.split("-"))
    today = date(year, month, 1)
    records = goal_budget_record.history(db, client_id)
    record = records[-1] if records else None
    near_years = (record.options or {}).get("near_years", DEFAULT_NEAR_YEARS) if record is not None and record.scenario_id == goal.id else DEFAULT_NEAR_YEARS
    events = list_goals(db, client_id)
    rows = []
    for event in sorted(events, key=lambda item: (item.target_date, item.id)):
        if event.direction != "expense":
            rows.append({"event_id": event.id, "name": event.name, "direction": "income", "kind": "income",
                         "allocation": 0.0, "source": None, "target_date": event.target_date.isoformat()})
            continue
        allocation, source = event_monthly_allocation(db, client_id, event, total, today)
        months = _months_between(period, event.target_date.strftime("%Y-%m"))
        kind = ("simulation_only" if event.budget_reflection_effective == "simulation_only"
                else "near" if near_years is None or months < near_years * 12 else "far")
        rows.append({"event_id": event.id, "name": event.name, "direction": "expense", "kind": kind,
                     "reflection": event.budget_reflection_effective, "allocation": round(allocation, 2),
                     "source": source, "target_date": event.target_date.isoformat()})
    summary = get_budget_summary(db, client_id, period)
    budget_total = 0.0
    lines = []
    for line in summary.get("plan_lines", []):
        if line.get("line_type") != "allocation":
            continue
        if line.get("target_type") != "capsule":
            account = ledger_service.get_account(db, client_id, line["account_id"]) if line.get("account_id") else None
            if account is None or account.account_type != "asset":
                continue
        amount = float(line.get("amount") or 0.0)
        if line.get("id") is None and not amount:
            # A definition not yet saved for the month still runs at its own amount.
            amount = float(line.get("recurring_amount") or 0.0)
        budget_total += amount
        lines.append({"name": line.get("target_name") or line.get("name"), "account_name": line.get("account_name"),
                      "amount": amount, "actual": float(line.get("actual") or 0.0), "source_kind": line.get("source_kind")})
    return {
        "goal": {"id": goal.id, "name": goal.name, "monthly_savings": total,
                 "monthly_savings_is_default": goal.monthly_savings_minor is None},
        "period": period,
        "near_years": near_years,
        "events": rows,
        "allocated_total": round(sum(row["allocation"] for row in rows), 2),
        "budget": {"total": round(budget_total, 2), "difference": round(budget_total - total, 2), "lines": lines},
        "reflection": None if record is None else {
            "applied_at": record.applied_at.isoformat(), "start_period": record.start_period,
            "end_period": record.end_period, "scenario_id": record.scenario_id, "options": record.options,
        },
        "reminders": _reminders(goal, total, events, records, period, budget_total),
    }
