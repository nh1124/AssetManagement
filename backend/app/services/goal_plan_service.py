"""Compute the plan the goal asks for, from its 積立設定 and its events' earmark settings.

For every month of the range:
- each goal expense event with ライフイベントへの取り崩し records gets an earmark row per
  account: the rest of what the records take from that account (− what the earmark holds
  there − what earlier months of the range already plan), spread evenly over the months
  left to the account's first withdrawal (R8). The earmark is the one made for the event
  (capsules.goal_event_id); apply creates it, named after the event, with a funding
  source per account;
- a withdrawal record's month gets a withdrawal row (取り崩し) for its account;
- each 使用口座 with a positive monthly amount gets an allocation row: the amount less
  what its earmarks take and less what the plan already puts into it otherwise
  (automatic transfers, rows typed by hand, earmarks the goal does not make), so the
  month's plan for the account comes to the 積立設定 (R7). Never below zero; a warning
  says when the rest already takes more;
- a negative monthly amount is a withdrawal row (取り崩し) of its size.
Only rows the goal wrote before (source "goal") are replaced; rows typed by hand stay.
Nothing changes until the user confirms the exact preview: apply recomputes it and
refuses when the fingerprint differs.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Refused
from ..domain.money import Money
from . import goal_budget_record
from .budget_plan_service import month_plan_lines
from .budget_plan_store import active_lines_for_periods
from .capsule_service import claimed_minor, goal_capsules
from .contribution_plan_service import event_withdrawals, resolve, withdrawals
from .goal_service import list_goals
from .life_scenario_scope import get_goal
from .money_storage import money_client_currency

GOAL_SOURCE = "goal"
REFLECTION_NOTIFICATION = "goal_reflection"
GOAL_LINE_NAME = "ゴールの積立"
GOAL_DRAWDOWN_NAME = "ゴールの取り崩し"
MAX_MONTHS = 24


def _index(period: str) -> int:
    year, month = (int(part) for part in period.split("-"))
    return year * 12 + month - 1


def _period(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _periods(start: str, end: str) -> list[str]:
    first, last = _index(start), _index(end)
    if last < first:
        raise Refused("終了月は開始月以降にしてください。", status_code=422)
    if last - first + 1 > MAX_MONTHS:
        raise Refused(f"一度に作れるのは{MAX_MONTHS}か月までです。", status_code=422)
    return [_period(index) for index in range(first, last + 1)]


def _goal(db: Session, client_id: int) -> models.LifeScenario:
    goal = get_goal(db, client_id)
    if goal is None:
        raise Refused("ゴールのシナリオが選ばれていません。", status_code=422)
    return goal


def earmarked_events(db: Session, client_id: int, goal: models.LifeScenario) -> list[models.LifeEvent]:
    """The goal's expense events that set money aside: those an account withdraws for."""
    events = [event for event in list_goals(db, client_id, goal.id) if event.direction == "expense"]
    taken = event_withdrawals(db, [event.id for event in events])
    return [event for event in events if taken.get(event.id)]


def earmark_schedule(db: Session, events: list[models.LifeEvent]) -> dict[int, dict[int, tuple[int, str]]]:
    """{event_id: {account_id: (minor, first month)}}: what each account withdraws for each event, and from when."""
    schedule: dict[int, dict[int, tuple[int, str]]] = {}
    for event_id, records in event_withdrawals(db, [event.id for event in events]).items():
        for record in records:
            minor, first = schedule.setdefault(event_id, {}).get(record.account_id, (0, record.start_period))
            schedule[event_id][record.account_id] = (minor - record.monthly_amount_minor, min(first, record.start_period))
    return schedule


def earmark_parts(db: Session, events: list[models.LifeEvent]) -> dict[int, dict[int, int]]:
    """{event_id: {account_id: minor}}: the earmark's target per account, what the records withdraw."""
    return {event_id: {account_id: minor for account_id, (minor, _) in accounts.items()}
            for event_id, accounts in earmark_schedule(db, events).items()}


def _other_allocations(db: Session, client_id: int, period: str, plan_id: int | None, tracked: set[int], currency: str) -> dict[int, int]:
    """{account_id: minor} the month's plan already sets aside into each account apart from the goal's own rows."""
    totals: dict[int, int] = {}
    for line in month_plan_lines(db, client_id, period, plan_id):
        if line.get("line_type") != "allocation" or not line.get("account_id") or GOAL_SOURCE in (line.get("source"), line.get("source_kind")):
            continue
        if line.get("target_type") == "capsule" and line.get("target_id") in tracked:
            continue
        if line.get("target_type") in {"account", "capsule"}:
            totals[line["account_id"]] = totals.get(line["account_id"], 0) + Money.from_major(str(line.get("budget_amount") or 0), currency).minor
    return totals


def _warning(message: str, periods: list[str]) -> str:
    when = periods[0] if len(periods) == 1 else f"{periods[0]}〜{periods[-1]}のうち{len(periods)}か月"
    return f"{when}：{message}"


def _stored_key(line: models.MonthlyPlanLine) -> tuple[str, str, int | None]:
    if line.target_type == "capsule":
        return "capsule", str(line.target_id), line.account_id
    return ("drawdown" if line.line_type == "drawdown" else "account"), "", line.account_id


def plan(db: Session, client_id: int, start: str, end: str, plan_id: int | None) -> dict:
    goal = _goal(db, client_id)
    periods = _periods(start, end)
    currency = money_client_currency(db, client_id)
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=goal.id).all()
    names = {account.id: account.name for account in db.query(models.Account).filter_by(client_id=client_id).all()}
    capsule_names = {capsule.id: capsule.name for capsule in db.query(models.Capsule).filter_by(client_id=client_id).all()}
    events = earmarked_events(db, client_id, goal)
    schedule = earmark_schedule(db, events)
    existing = goal_capsules(db, client_id, [event.id for event in events])
    tracked = {capsule.id for capsule in existing.values()}
    claims = {(event.id, account_id): claimed_minor(db, client_id, existing[event.id].id, account_id).get(currency, 0)
              if event.id in existing else 0
              for event in events for account_id in schedule[event.id]}
    taken_out = withdrawals(plans)
    stored = [line for line in active_lines_for_periods(db, client_id, plan_id, periods) if line.source_kind == GOAL_SOURCE]
    planned: dict[tuple[int, int], int] = {}
    changes, months = [], []
    warned: dict[str, list[str]] = {}
    for period in periods:
        wanted: dict[tuple[str, str, int | None], int] = {}
        made_for: dict[tuple[str, str, int | None], models.LifeEvent] = {}
        taken: dict[int, int] = {}
        for event in events:
            capsule = existing.get(event.id)
            for account_id, (target, first) in schedule[event.id].items():
                left = _index(first) - _index(period)
                if left < 0:
                    continue
                part = (event.id, account_id)
                remaining = max(0, target - claims[part] - planned.get(part, 0))
                monthly = remaining // max(1, left)
                planned[part] = planned.get(part, 0) + monthly
                key = ("capsule", str(capsule.id) if capsule is not None else f"event:{event.id}", account_id)
                wanted[key] = monthly
                made_for[key] = event
                taken[account_id] = taken.get(account_id, 0) + monthly
        contribution_total = 0
        for record in taken_out:
            if record.start_period == period:
                key = ("drawdown", "", record.account_id)
                wanted[key] = wanted.get(key, 0) - record.monthly_amount_minor
        other = _other_allocations(db, client_id, period, plan_id, tracked, currency)
        for account_id in sorted({plan.account_id for plan in plans}):
            contribution = resolve(plans, account_id, period, goal.annual_return)[0]
            contribution_total += contribution
            if contribution < 0:
                wanted[("drawdown", "", account_id)] = wanted.get(("drawdown", "", account_id), 0) - contribution
                continue
            used = taken.get(account_id, 0) + other.get(account_id, 0)
            if used > contribution:
                warned.setdefault(f"「{names.get(account_id, account_id)}」は取り置きと既存の配分（自動取引など）が積立設定の月額を超えています。", []).append(period)
            if contribution:
                wanted[("account", "", account_id)] = max(0, contribution - used)
        rows = {_stored_key(line): line for line in stored if line.target_period == period}
        for key in sorted(set(wanted) | set(rows), key=lambda item: (item[0], item[1], item[2] or 0)):
            kind, target, account_id = key
            line = rows.get(key)
            current = line.amount_minor if line is not None else 0
            new = wanted.get(key, 0)
            if line is None and new == 0:
                continue
            event = made_for.get(key)
            capsule_id = int(target) if kind == "capsule" and target.isdigit() else None
            changes.append({
                "period": period, "kind": kind, "account_id": account_id, "account_name": names.get(account_id),
                "capsule_id": capsule_id, "event_id": event.id if event is not None else None,
                "capsule_name": capsule_names.get(capsule_id) if capsule_id else (event.name if event is not None else None),
                "new_capsule": kind == "capsule" and capsule_id is None,
                "line_id": line.id if line is not None else None,
                "current": Money(current, currency).to_float(), "new": Money(new, currency).to_float(),
                "current_minor": current, "new_minor": new, "changed": line is None or current != new or key not in wanted,
                "retire": key not in wanted,
            })
        months.append({"period": period, "contribution": Money(contribution_total, currency).to_float(),
                       "earmarks": Money(sum(minor for key, minor in wanted.items() if key[0] == "capsule"), currency).to_float()})
    basis = {"scenario_id": goal.id, "periods": periods,
             "changes": [{key: change[key] for key in ("period", "kind", "account_id", "capsule_id", "event_id", "line_id", "current_minor", "new_minor", "retire")}
                         for change in changes]}
    fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
    return {"scenario": {"id": goal.id, "name": goal.name}, "periods": periods, "currency": currency,
            "months": months, "changes": changes, "warnings": [_warning(message, sorted(set(when))) for message, when in warned.items()],
            "fingerprint": fingerprint}


def plan_check(db: Session, client_id: int, period: str) -> dict:
    """Per account: what the goal's 積立設定 sets aside (or withdraws) this month, and what the plan does."""
    goal = get_goal(db, client_id)
    currency = money_client_currency(db, client_id)
    if goal is None:
        return {"period": period, "goal": None, "accounts": [], "contribution": 0.0, "planned": 0.0, "difference": 0.0}
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=goal.id).all()
    planned: dict[int, float] = {}
    for line in month_plan_lines(db, client_id, period):
        if not line.get("account_id") or line.get("target_type") not in {"account", "capsule"}:
            continue
        sign = 1 if line.get("line_type") == "allocation" else -1 if line.get("line_type") == "drawdown" else 0
        if sign:
            planned[line["account_id"]] = planned.get(line["account_id"], 0.0) + sign * float(line.get("budget_amount") or 0.0)
    accounts = {account.id: account for account in db.query(models.Account).filter_by(client_id=client_id, account_type="asset").all()}
    rows = []
    for account_id in sorted(set(planned) | {plan.account_id for plan in plans}):
        if account_id not in accounts:
            continue
        contribution = Money(resolve(plans, account_id, period, goal.annual_return)[0], currency).to_float()
        plan_amount = round(planned.get(account_id, 0.0), 2)
        if contribution or plan_amount:
            rows.append({"account_id": account_id, "name": accounts[account_id].name, "contribution": contribution,
                         "planned": plan_amount, "difference": round(plan_amount - contribution, 2)})
    contribution = round(sum(row["contribution"] for row in rows), 2)
    total = round(sum(row["planned"] for row in rows), 2)
    return {"period": period, "goal": {"id": goal.id, "name": goal.name}, "accounts": rows,
            "contribution": contribution, "planned": total, "difference": round(total - contribution, 2),
            "reflected": goal_budget_record.covering(db, client_id, period) is not None}


def reflection_notifications(db: Session, client_id: int, period: str) -> list[dict]:
    """One reminder while the goal sets money aside and no reflection covers this month."""
    goal = get_goal(db, client_id)
    if goal is None or goal_budget_record.covering(db, client_id, period) is not None:
        return []
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=goal.id).all()
    if not any(resolve(plans, account_id, period, goal.annual_return)[0] for account_id in {plan.account_id for plan in plans}):
        return []
    return [{
        "dedupe_key": f"{REFLECTION_NOTIFICATION}:{goal.id}:{period}",
        "title": "ゴールから計画を作る時期です",
        "body": f"{period} の計画にゴール「{goal.name}」の積立設定がまだ反映されていません。",
        "payload": {"period": period, "scenario_id": goal.id},
        "link": "/plan",
    }]
