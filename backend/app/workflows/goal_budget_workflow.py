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
from datetime import date, datetime
from uuid import uuid4

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
    retire_plan_lines,
    update_plan_lines,
)
from ..services.cache_service import invalidate_client
from ..services import goal_baseline_service, goal_budget_record, life_scenario_service, monthly_action_store
from ..services.budget_plan_service import get_budget_summary
from ..services.goal_service import list_goals
from ..services.life_scenario_scope import get_goal
from ..services.strategy_service import DEFAULT_NEAR_YEARS, event_monthly_allocation
from .. import schemas
from ..services.goal_budget_inputs import goal_budget_inputs, near_monthly_minor
from .capsule_workflow import set_account_claim
from ..services.goal_service import get_life_event
from ..services.life_scenario_scope import lock_client
from ..services.money_storage import money_client_currency

GOAL_SOURCE = "goal"
REFLECTION_ACTION = "goal_reflection"
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


def _contributes(period: str, start: str, target) -> bool:
    """A near event is funded in each month before its target month (or only the first, if due then)."""
    return _months_between(period, target.strftime("%Y-%m")) >= 1 or period == start


def _capsule_rows(lines, period: str, capsule, event_id: int, amount: Money) -> list[dict]:
    """The plan rows this capsule needs in the month: update, create, or retire.

    Stored rows may target the capsule (one per funding account, or one without an
    account from before funding plans) or, in the oldest form, the life event itself.
    """
    if capsule is None:
        # Created on apply: no funding plan yet, so one row for the whole amount.
        return [{"account_id": None, "line": None, "amount": amount}]
    stored = [line for line in lines if line.target_period == period and line.line_type == "allocation"
              and ((line.target_type == "capsule" and line.target_id == capsule.id)
                   or (line.target_type == "life_event" and line.target_id == event_id))]
    by_account = {line.account_id: line for line in stored if line.account_id is not None}
    legacy = [line for line in stored if line.account_id is None]
    retire = [{"account_id": None, "line": line, "amount": None} for line in legacy]
    if legacy and not by_account and len(capsule.funding_sources) <= 1:
        # The account-less row stands for the whole capsule; keep the first, retire duplicates.
        return [{"account_id": None, "line": legacy[0], "amount": amount}, *retire[1:]]
    # With account rows, or several funding accounts, an account-less row cannot be
    # updated; it is retired and the capsule gets one row per account instead.
    rows = [{"account_id": account_id, "line": by_account.get(account_id) if account_id is not None else None, "amount": part}
            for account_id, part in capsule_shares(capsule, amount)]
    return [*rows, *retire]


def _budget_rows(db: Session, client_id: int, period: str, plan_id: int | None) -> list[dict]:
    """The month's savings as the budget shows it: allocation rows into capsules or asset accounts.

    Read through the budget summary so stored rows, definitions merged into them and
    capsules' own amounts are each counted once, exactly as the budget page lists them.
    A definition not yet saved for the month runs at its own amount.
    """
    if plan_id is None:
        return []
    summary = get_budget_summary(db, client_id, period, plan_id=plan_id, cash_flow_months=1)
    rows = []
    for line in summary.get("plan_lines", []):
        if line.get("line_type") != "allocation":
            continue
        if line.get("target_type") != "capsule":
            account = ledger_service.get_account(db, client_id, line["account_id"]) if line.get("account_id") else None
            if account is None or account.account_type != "asset":
                continue
        amount = float(line.get("amount") or 0.0)
        if line.get("id") is None and not amount:
            amount = float(line.get("recurring_amount") or 0.0)
        rows.append({**line, "resolved_amount": amount})
    return rows


def _existing_savings(db: Session, client_id: int, periods: list[str], plan_id: int | None,
                      skip_capsules: set[int], currency: str) -> list[dict]:
    """Savings the budget already plans in these months, outside what this reflection writes.

    The budget keeps one row per account for definitions: a definition into an
    account merges with the row stored for it, and the stored amount stands. A goal
    row on such an account therefore carries the definition too; its definition part
    is still existing savings, read from the merged row's definition amount.
    """
    groups: dict[str, dict] = {}
    entries = registry_service.list_entries(db, client_id)
    entry_names = {entry.id: entry.name for entry in entries}

    def group(key: str, **fields) -> dict:
        return groups.setdefault(key, {"key": key, "amounts": dict.fromkeys(periods, 0), "line_ids": {},
                                       "updatable": False, "current_amount": None, **fields})

    for period in periods:
        for line in _budget_rows(db, client_id, period, plan_id):
            target_type, target_id = line.get("target_type"), line.get("target_id")
            ids = sorted(line.get("registry_entry_ids") or [])
            amount = line["resolved_amount"]
            if line.get("source_kind") == GOAL_SOURCE:
                if not ids:
                    continue
                # Only the definition part of a merged goal row is existing savings.
                amount = float(line.get("registry_amount") or line.get("recurring_amount") or 0.0)
            if target_type == "capsule" and target_id in skip_capsules:
                continue
            name = line.get("target_name") or line.get("name") or ""
            if ids:
                row = group("definition:" + ",".join(str(value) for value in ids), kind="definition",
                            id=ids[0] if len(ids) == 1 else None, account_id=line.get("account_id"),
                            name="、".join(entry_names.get(value, name) for value in ids))
            elif target_type == "capsule":
                row = group(f"capsule:{target_id}", kind="capsule", id=target_id, name=name, account_id=None)
            else:
                row = group(f"manual:{line.get('account_id')}:{(line.get('name') or '').strip()}", kind="manual",
                            id=None, name=name, account_id=line.get("account_id"))
            row["amounts"][period] += Money.from_float(float(amount), currency).minor
            if line.get("id") is not None:
                row["line_ids"].setdefault(period, []).append(line["id"])
    # A plain monthly definition into an asset account can carry the goal savings,
    # including one the goal set to zero last time.
    for entry in entries:
        if (entry.line_type != "allocation" or not entry.is_active or not entry.budget_active
                or (entry.frequency or "Monthly") != "Monthly" or entry.currency != currency):
            continue
        account_id = registry_service.registry_target_account_id(entry)
        account = ledger_service.get_account(db, client_id, account_id) if account_id else None
        if account is None or account.account_type != "asset":
            continue
        row = group(f"definition:{entry.id}", kind="definition", id=entry.id, name=entry.name, account_id=account_id)
        row["updatable"] = True
        row["current_amount"] = entry.amount
    return list(groups.values())


def _plan(db: Session, client_id: int, options: dict, plan_id: int | None) -> dict:
    currency = money_client_currency(db, client_id)
    inputs = goal_budget_inputs(db, client_id, start_period=options["start_period"], near_years=options["near_years"])
    if inputs["scenario"] is None:
        raise Refused("ゴールのシナリオがありません。シナリオ一覧でゴールを選んでください。", status_code=422)
    periods = _periods(options["start_period"], options["months"])
    start = periods[0]
    lines = active_lines_for_periods(db, client_id, plan_id, periods)
    create_for = set(options.get("create_capsules") or [])
    events = inputs["events"]

    funded_rows = []  # (event row, capsule or None)
    for row in events:
        if row["direction"] != "expense" or row["status"] != "reflected" or not row["near"]:
            continue
        if row["capsule_id"] is None and row["event_id"] not in create_for:
            row["status"] = "no_capsule"
            continue
        capsule = capsule_service.get_capsule(db, client_id, row["capsule_id"]) if row["capsule_id"] else None
        row["create_capsule"] = capsule is None
        funded_rows.append((row, capsule))
    suggestions, handovers = _handovers(db, client_id, options, funded_rows, currency)
    # An event left without a capsule still needs its money; the total counts it.
    required_minor = sum(row["monthly_required_minor"] for row in events
                         if row["direction"] == "expense" and row["status"] in {"reflected", "no_capsule"})
    funded_capsules = [(row, capsule, Money(row["monthly_required_minor"], currency)) for row, capsule in funded_rows]
    target_dates = {row["event_id"]: date.fromisoformat(row["target_date"]) for row in events}

    def contribution(row: dict, amount: Money, period: str) -> Money:
        return amount if _contributes(period, start, target_dates[row["event_id"]]) else Money(0, currency)

    scenario_minor = Money.from_float(float(inputs["scenario"]["monthly_savings"]), currency).minor
    chosen_minor = scenario_minor if options["savings_source"] == "scenario" else required_minor
    # A capsule is funded only until its target month; later months go to the rest.
    capsule_minor = {period: sum(contribution(row, amount, period).minor for row, _, amount in funded_capsules)
                     for period in periods}

    account = None
    if options.get("savings_account_id") is not None:
        if options.get("savings_definition_id") is not None:
            raise Refused("積立先は口座か定義のどちらか一方を選んでください。", status_code=422)
        account = ledger_service.get_account(db, client_id, options["savings_account_id"])
        if account is None or account.account_type != "asset" or not account.is_active:
            raise NotFound("積立先には有効な資産口座を選んでください。")

    funded_ids = {capsule.id for _, capsule, _ in funded_capsules if capsule is not None}
    existing = _existing_savings(db, client_id, periods, plan_id, funded_ids, currency)
    definition = None
    if options.get("savings_definition_id") is not None:
        definition = next((row for row in existing if row["kind"] == "definition" and row["updatable"]
                           and row["id"] == options["savings_definition_id"]), None)
        if definition is None:
            raise NotFound("積立先の定義は、資産口座への毎月の配分の定義から選んでください。")
    uncounted = set(options.get("uncounted") or [])
    for row in existing:
        row["destination"] = row is definition
        # The destination definition is rewritten below, so it is not also counted.
        row["counted"] = row["key"] not in uncounted and not row["destination"]
    counted = {period: sum(row["amounts"][period] for row in existing if row["counted"]) for period in periods}
    residual = {period: max(0, chosen_minor - capsule_minor[period] - counted[period]) for period in periods}
    if definition is not None and len(set(residual.values())) > 1:
        # A definition holds one amount for every month; it cannot follow a changing rest.
        raise Refused("反映する期間の中で残りの積立額が月ごとに変わるため、定義を積立先にできません。"
                      "反映する期間を1か月にするか、口座を積立先にしてください。", status_code=422)
    account_minor = residual[start]
    # How each event is funded each month, as event progress will read it: a near
    # event by its capsule, a far one by its priority share of everything else
    # saved (existing savings and the goal row alike), in the first month.
    funded_events = {row["event_id"] for row, _, _ in funded_capsules}
    far = [row for row in events if row["direction"] == "expense" and row["status"] == "reflected" and not row["near"]]
    far_pool = max(0, chosen_minor - capsule_minor[start])
    weights = [PRIORITY_WEIGHTS.get(row["priority"], 1) for row in far]
    shares = Money(far_pool, currency).allocate(weights) if far and sum(weights) else []
    far_share = {row["event_id"]: share.minor for row, share in zip(far, shares)}
    for row in events:
        if row["event_id"] in funded_events:
            row["allocation_minor"] = row["monthly_required_minor"]
        else:
            row["allocation_minor"] = far_share.get(row["event_id"], 0)

    def retire(period: str, line) -> dict:
        return {"period": period, "kind": "retire", "event_id": None, "capsule_id": None,
                "name": line.name, "account_id": line.account_id, "line_id": line.id,
                "current_amount": line.amount, "new_amount": 0.0}

    changes = []
    for period in periods:
        for row, capsule, amount in funded_capsules:
            for item in _capsule_rows(lines, period, capsule, row["event_id"], contribution(row, amount, period)):
                line = item["line"]
                if item["amount"] is None:
                    changes.append(retire(period, line))
                    continue
                changes.append({
                    "period": period, "kind": "capsule", "event_id": row["event_id"],
                    "capsule_id": capsule.id if capsule else None,
                    "name": capsule.name if capsule else row["name"],
                    "account_id": item["account_id"] if line is None else line.account_id,
                    "line_id": line.id if line is not None else None,
                    "current_amount": line.amount if line is not None else None,
                    "new_amount": _major(item["amount"].minor, currency),
                })
        goal_lines = [line for line in lines if line.target_period == period and line.source_kind == GOAL_SOURCE]
        if definition is not None:
            # The definition now carries the goal savings; an earlier goal row would double it.
            changes.extend(retire(period, old) for old in goal_lines)
            # Months already saved with the definition's old amount follow the new one.
            for line_id in definition["line_ids"].get(period, []):
                line = next((item for item in lines if item.id == line_id), None)
                changes.append({
                    "period": period, "kind": "definition_row", "event_id": None, "capsule_id": None,
                    "definition_id": definition["id"], "name": definition["name"], "account_id": definition["account_id"],
                    "line_id": line_id, "current_amount": line.amount if line is not None else None,
                    "new_amount": _major(residual[period], currency),
                })
        if account is not None:
            line = next((line for line in goal_lines if line.account_id == account.id), None)
            # The budget shows one row for this account, so definitions into it ride along.
            merged = sum(row["amounts"][period] for row in existing
                         if row["kind"] == "definition" and row["counted"] and row["account_id"] == account.id)
            changes.append({
                "period": period, "kind": "savings", "event_id": None, "capsule_id": None,
                "name": GOAL_LINE_NAME, "account_id": account.id,
                "line_id": line.id if line is not None else None,
                "current_amount": line.amount if line is not None else None,
                "new_amount": _major(residual[period] + merged, currency),
                "includes_definitions": _major(merged, currency),
            })
            # An earlier reflection to another account is replaced, not added to.
            changes.extend(retire(period, old) for old in goal_lines if old.account_id != account.id)
    for item in handovers:
        changes.append({
            "period": start, "kind": "claim", "event_id": item["event_id"], "capsule_id": item["capsule_id"],
            "name": item["name"], "account_id": item["account_id"], "line_id": None,
            "current_amount": _major(item["claimed_minor"], currency),
            "new_amount": _major(item["claimed_minor"] + item["amount_minor"], currency),
        })
    if definition is not None:
        changes.append({
            "period": start, "kind": "definition", "event_id": None, "capsule_id": None,
            "definition_id": definition["id"], "name": definition["name"], "account_id": definition["account_id"],
            "line_id": None, "current_amount": definition["current_amount"],
            "new_amount": _major(residual[start], currency),
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
        "handovers": sorted(({"event_id": item["event_id"], "account_id": item["account_id"],
                              "amount": _major(item["amount_minor"], currency)} for item in handovers),
                            key=lambda item: item["event_id"]),
        "create_capsules": sorted(row["event_id"] for row, capsule, _ in funded_capsules if capsule is None),
    }
    # Everything that decides what is written or recorded, so apply can refuse a changed plan.
    fingerprint = hashlib.sha256(json.dumps({"options": normalized, "events": [
        {key: row.get(key) for key in ("event_id", "status", "monthly_required_minor", "allocation_minor", "priority",
                                       "capsule_id", "target_amount", "target_date")} for row in events
    ], "existing": existing, "changes": changes, "handovers": handovers,
        "suggestions": suggestions}, sort_keys=True, default=str).encode()).hexdigest()
    existing_out = [{**{key: row[key] for key in ("key", "kind", "id", "name", "account_id", "updatable", "counted", "destination")},
                     "amount": _major(row["amounts"][start], currency)} for row in existing
                    if row["destination"] or row["updatable"] or any(row["amounts"].values())]
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
            "capsule_amount": _major(capsule_minor[start], currency),
            "account_amount": _major(account_minor, currency),
            # Existing savings and near capsules already exceed the monthly savings chosen.
            "shortfall": _major(max(0, capsule_minor[start] + counted[start] - chosen_minor), currency),
            "account_required": account is None and definition is None and account_minor > 0,
            "suggested_account_id": previous_account,
        },
        "events": events,
        "existing": existing_out,
        "handover_suggestions": [_handover_out(item, currency) for item in suggestions],
        "handovers": [_handover_out(item, currency) for item in handovers],
        "changes": changes,
        "fingerprint": fingerprint,
        "_funded_capsules": funded_capsules,
        "_handovers": handovers,
    }


def _available_minor(db: Session, client_id: int, account_id: int, currency: str) -> int:
    """What an account holds that no capsule has claimed yet."""
    balance = ledger_service.account_balances_minor(db, client_id, account_id).get(currency, 0)
    claimed = capsule_service.account_claimed_minor(db, client_id, account_id).get(currency, 0)
    return max(0, balance - claimed)


def _handover_out(item: dict, currency: str) -> dict:
    major = {key[:-6]: _major(value, currency) for key, value in item.items() if key.endswith("_minor")}
    return {key: value for key, value in item.items() if not key.endswith("_minor")} | major


def _handovers(db: Session, client_id: int, options: dict, funded_rows, currency: str) -> tuple[list[dict], list[dict]]:
    """Suggested and chosen handovers into near capsules, and their effect on each monthly amount.

    When an event leaves the far range, the money earlier reflections planned for it
    sits in the savings, not in its capsule. The suggestion is to claim that much of
    the savings account for the capsule (no money moves), capped by what the account
    holds unclaimed and by what the event still needs. The user confirms or edits each
    one; a chosen handover counts as funded, so the event's monthly amount drops.
    """
    records = goal_budget_record.history(db, client_id)
    period = options["start_period"]
    last = records[-1] if records else None
    default_account = (options.get("savings_account_id")
                       or ((last.options or {}).get("savings_account_id") if last is not None else None))
    rows = {row["event_id"]: (row, capsule) for row, capsule in funded_rows}
    available: dict[int, int] = {}

    def free(account_id: int) -> int:
        if account_id not in available:
            available[account_id] = _available_minor(db, client_id, account_id, currency)
        return available[account_id]

    def need_minor(row: dict) -> int:
        return max(0, Money.from_float(float(row["target_amount"]) - float(row["funded"]), currency).minor)

    suggestions = []
    for event_id, (row, capsule) in rows.items():
        handed = sum(float(item.get("handover") or 0.0) for record in records for item in record.events or []
                     if item.get("lineage") == row["lineage"])
        planned = Money.from_float(max(0.0, _planned_far_savings(records, row["lineage"], period) - handed), currency).minor
        if planned <= 0:
            continue
        cap = min(planned, need_minor(row), free(default_account) if default_account else planned)
        suggestions.append({"event_id": event_id, "name": row["name"], "account_id": default_account,
                            "planned_minor": planned, "suggested_minor": max(0, cap)})

    chosen, used = [], {}
    for item in options.get("handovers") or []:
        if item["event_id"] not in rows:
            raise Refused("引き継ぎは、取り置きで積み立てる近いライフイベントにだけ指定できます。", status_code=422)
        row, capsule = rows[item["event_id"]]
        account = ledger_service.get_account(db, client_id, item["account_id"])
        if account is None or account.account_type != "asset" or not account.is_active:
            raise NotFound("引き継ぎ元には有効な資産口座を選んでください。")
        amount = Money.from_float(float(item["amount"]), currency).minor
        if amount <= 0:
            continue
        if amount > need_minor(row):
            raise Refused(f"「{row['name']}」の引き継ぎ額が目標額までの不足を超えています。", status_code=422)
        used[account.id] = used.get(account.id, 0) + amount
        if used[account.id] > free(account.id):
            raise Refused(f"「{account.name}」で確保できる残高（{_major(free(account.id), currency):,.0f}）を超えています。", status_code=422)
        sources = list(capsule.funding_sources) if capsule is not None else []
        adds_source = all(source.account_id != account.id for source in sources)
        if adds_source and sources and not any(source.target_amount_minor for source in sources):
            # Equal shares would start including the new account and change the capsule's plan rows.
            raise Refused(f"「{row['name']}」の取り置きは資金源の配分が未設定のため、別の口座から引き継げません。"
                          "取り置きの画面で資金源を設定してください。", status_code=422)
        claimed = capsule_service.claimed_minor(db, client_id, capsule.id, account.id).get(currency, 0) if capsule else 0
        before = row["monthly_required_minor"]
        after = near_monthly_minor(_major(need_minor(row) - amount, currency), row["months"], currency)
        row["monthly_required_minor"] = after
        row["handover"] = _major(amount, currency)
        chosen.append({"event_id": row["event_id"], "name": row["name"], "capsule_id": capsule.id if capsule else None,
                       "account_id": account.id, "account_name": account.name, "adds_funding_source": adds_source,
                       "amount_minor": amount, "claimed_minor": claimed,
                       "available_before_minor": free(account.id) - used[account.id] + amount,
                       "available_after_minor": free(account.id) - used[account.id],
                       "funded_before_minor": Money.from_float(float(row["funded"]), currency).minor,
                       "funded_after_minor": Money.from_float(float(row["funded"]), currency).minor + amount,
                       "monthly_before_minor": before, "monthly_after_minor": after})
    return suggestions, chosen


def _claim(db: Session, client_id: int, item: dict, capsule, currency: str) -> None:
    """Claim part of an account for a capsule, adding the account as a zero-share funding source if needed."""
    if all(source.account_id != item["account_id"] for source in capsule.funding_sources):
        sources = [schemas.CapsuleFundingSourceInput(
            account_id=source.account_id, target_amount=source.target_amount or 0.0,
            max_share_bp=source.max_share_bp, sort_order=source.sort_order,
        ) for source in sorted(capsule.funding_sources, key=lambda source: (source.sort_order, source.id))]
        # A zero target keeps the capsule's monthly rows on the accounts that fund it.
        sources.append(schemas.CapsuleFundingSourceInput(
            account_id=item["account_id"], target_amount=0.0,
            sort_order=max((source.sort_order for source in sources), default=-1) + 1,
        ))
        capsule_service.set_funding_sources(db, client_id, capsule.id, sources, commit=False)
        db.refresh(capsule)
    current = capsule_service.claimed_minor(db, client_id, capsule.id, item["account_id"]).get(currency, 0)
    set_account_claim(db, client_id, capsule.id, account_id=item["account_id"],
                      target_amount=_major(current + item["amount_minor"], currency), commit=False)


def preview(db: Session, client_id: int, options: dict) -> dict:
    """Everything a reflection would do, computed against the plan without writing.

    A client without a budget plan gets one when the reflection is applied, and
    the budget then lists its definitions and capsules. The preview sees the same
    by creating that plan inside a savepoint it always rolls back.
    """
    plan_id = find_budget_plan_id(db, client_id)
    if plan_id is not None:
        result = _plan(db, client_id, options, plan_id)
    else:
        nested = db.begin_nested()
        try:
            result = _plan(db, client_id, options, resolve_budget_plan_id(db, client_id, commit=False))
        finally:
            nested.rollback()
    result.pop("_funded_capsules")
    result.pop("_handovers")
    return result


def apply(db: Session, client_id: int, options: dict, fingerprint: str, *, update_baseline: bool = False) -> dict:
    lock_client(db, client_id)
    try:
        # The plan the preview read is the plan written; only a client without any
        # plan gets its first one, inside this transaction, as the preview assumed.
        plan_id = find_budget_plan_id(db, client_id)
        if plan_id is None:
            plan_id = resolve_budget_plan_id(db, client_id, commit=False)
        planned = _plan(db, client_id, options, plan_id)
        if planned["fingerprint"] != fingerprint:
            raise Conflict("ゴールか予算の内容が確認後に変わりました。もう一度確認してください。")
        currency = money_client_currency(db, client_id)
        created_capsules = {}
        for row, capsule, _ in planned["_funded_capsules"]:
            if capsule is None:
                event = get_life_event(db, client_id, row["event_id"])
                created_capsules[row["event_id"]] = capsule_service.create_capsule_for_goal(db, client_id, event)
        # Claims first: a capsule may gain the account as a funding source before its rows are written.
        for item in planned["_handovers"]:
            capsule = (capsule_service.get_capsule(db, client_id, item["capsule_id"]) if item["capsule_id"]
                       else created_capsules[item["event_id"]])
            _claim(db, client_id, item, capsule, currency)
        creates, updates, definitions = [], [], []
        for change in planned["changes"]:
            if not change["changed"]:
                continue
            if change["kind"] == "definition":
                definitions.append(change)
                continue
            if change["kind"] == "claim":
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
            # Retire first so a replacement row never meets the row it replaces.
            retires = [item["id"] for item in updates if item.get("is_active") is False]
            if retires:
                retire_plan_lines(db, client_id, retires, commit=False)
            amounts = [item for item in updates if item.get("is_active") is not False]
            if amounts:
                update_plan_lines(db, client_id, amounts, commit=False)
            if creates:
                create_plan_lines(db, client_id, creates, commit=False)
            for change in definitions:
                registry_service.update_entry(db, client_id, change["definition_id"], {"amount": change["new_amount"]}, commit=False)
            record = goal_budget_record.record(
                db, client_id, scenario_id=planned["scenario"]["id"], start_period=planned["periods"][0],
                end_period=planned["periods"][-1], options=planned["options"], summary=planned["savings"],
                events=[{key: row.get(key) for key in (
                    "event_id", "lineage", "name", "direction", "status", "near", "monthly_required", "allocation",
                    "target_amount", "target_date", "handover",
                )} for row in planned["events"]],
            )
            if update_baseline:
                # Q4: the user may move the baseline to the plan the budget now follows.
                goal_baseline_service.capture(db, client_id, "reflection")
            # A confirmed reflection completes the actions that asked for it.
            for action in monthly_action_store.pending_of_kind(db, client_id, REFLECTION_ACTION):
                monthly_action_store.update(db, client_id, action, {
                    "status": "applied", "applied_at": datetime.utcnow(),
                    "result": {"reflection_id": record.id, "periods": planned["periods"]},
                })
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
        "handovers": len(planned["_handovers"]),
        "created_capsules": [{"event_id": event_id, "capsule_id": capsule.id, "name": capsule.name}
                             for event_id, capsule in created_capsules.items()],
        "periods": planned["periods"],
        "currency": currency,
    }


def _months_between(start: str, end: str) -> int:
    (start_year, start_month), (end_year, end_month) = ((int(part) for part in value.split("-")) for value in (start, end))
    return (end_year - start_year) * 12 + (end_month - start_month)


def _planned_far_savings(records, lineage: str, period: str) -> float:
    """What earlier reflections set aside for an event while it was far, month by month.

    A month is counted once, from the latest reflection covering it, and only months
    before the given one -- those have already been saved.
    """
    by_month: dict[str, object] = {}
    for row in records:  # oldest first, so a later reflection replaces an earlier one
        month = row.start_period
        while month <= row.end_period:
            by_month[month] = row
            month = _periods(month, 2)[1]
    total = 0.0
    for month, row in by_month.items():
        if month >= period:
            continue
        entry = next((item for item in row.events or [] if item.get("lineage") == lineage), None)
        if entry is not None and not entry.get("near") and entry.get("status") == "reflected":
            total += float(entry.get("allocation") or 0.0)
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
                handed = sum(float(item.get("handover") or 0.0) for record in records for item in record.events or []
                             if item.get("lineage") == event.lineage)
                handover = max(0.0, _planned_far_savings(records, event.lineage, period) - handed)
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
    budget_rows = _budget_rows(db, client_id, period, find_budget_plan_id(db, client_id))
    budget_total = sum(line["resolved_amount"] for line in budget_rows)
    lines = [{"name": line.get("target_name") or line.get("name"), "account_name": line.get("account_name"),
              "amount": line["resolved_amount"], "actual": float(line.get("actual") or 0.0),
              "source_kind": line.get("source_kind")} for line in budget_rows]
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


def sync_reflection_action(db: Session, client_id: int, period: str) -> dict:
    """Keep one pending "update the budget from the goal" action while reasons exist.

    Called when the user opens the actions, goal or budget screen for the month, so
    a reminder becomes an action without a background job writing to clients
    nobody is using. The action needs confirmation: it opens the reflection preview
    and is completed by apply(); when the reasons go away it is set aside.
    """
    reminders = status(db, client_id, period)["reminders"]
    pending = monthly_action_store.pending_of_kind(db, client_id, REFLECTION_ACTION)
    try:
        if reminders:
            description = "ゴールから予算を更新（確認が必要）"
            payload = {"period": period, "reminders": reminders}
            if pending:
                monthly_action_store.update(db, client_id, pending[0], {
                    "description": description, "payload": payload, "target_period": period,
                })
                action = pending[0]
            else:
                action = monthly_action_store.create(db, client_id, {
                    "source_period": period, "target_period": period, "kind": REFLECTION_ACTION,
                    "description": description, "payload": payload, "result": {}, "status": "pending",
                    "proposal_id": f"goal_reflection_{uuid4().hex[:10]}",
                    "idempotency_key": f"goal_reflection:{client_id}:{period}:{uuid4().hex}",
                })
            for extra in pending[1:]:
                monthly_action_store.update(db, client_id, extra, {"status": "skipped", "result": {"reason": "重複"}})
        else:
            action = None
            for row in pending:
                monthly_action_store.update(db, client_id, row, {
                    "status": "skipped", "result": {"reason": "お知らせが解消されたため"},
                })
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"action_id": action.id if action is not None else None, "reminders": len(reminders)}
