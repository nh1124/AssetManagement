"""Compute the plan the goal asks for: its 積立設定 per account and its earmark tracking.

For every month of the range:
- each linked earmark is planned the rest of what its events need, spread evenly over
  the months left to each event (an event's remaining need = target − its share of the
  earmarks' claims − what earlier months of the range already plan for it, divided
  among its earmarks by share), from the earmark's funding accounts;
- each account with a contribution is planned that contribution less what its
  earmarks take from it and less what the plan already puts into it otherwise
  (automatic transfers, rows typed by hand, earmarks the goal does not track), so
  the month's plan for the account comes to the contribution; never below zero,
  and a warning says when the rest already takes more.
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
from .budget_lines import capsule_shares
from .budget_plan_service import month_plan_lines
from .budget_plan_store import active_lines_for_periods
from .capsule_service import claimed_minor
from .contribution_plan_service import resolve
from .goal_service import list_goals
from .life_scenario_scope import get_goal
from .money_storage import money_client_currency

GOAL_SOURCE = "goal"
REFLECTION_NOTIFICATION = "goal_reflection"
GOAL_LINE_NAME = "ゴールの積立"
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


def _earmark_minor(db: Session, client_id: int, goal: models.LifeScenario, period: str, currency: str,
                   claims: dict[int, int], planned: dict[int, int]) -> dict[int, int]:
    """{capsule_id: minor} the earmarks need this month for the goal's expense events.

    planned carries, per event, what earlier months of the same range set aside, so
    the months share the remaining need equally instead of each asking for more.
    """
    events = [event for event in list_goals(db, client_id, goal.id) if event.direction == "expense" and event.target_date]
    links = db.query(models.GoalEventEarmark).filter(
        models.GoalEventEarmark.client_id == client_id,
        models.GoalEventEarmark.life_event_id.in_([event.id for event in events]),
    ).order_by(models.GoalEventEarmark.id).all()
    by_event: dict[int, list[models.GoalEventEarmark]] = {}
    for link in links:
        by_event.setdefault(link.life_event_id, []).append(link)
    amounts: dict[int, int] = {}
    for event in events:
        months = _index(event.target_date.strftime("%Y-%m")) - _index(period)
        own = [link for link in by_event.get(event.id, []) if link.share_bp > 0]
        if months < 0 or not own:
            continue
        for link in own:
            if link.capsule_id not in claims:
                claims[link.capsule_id] = claimed_minor(db, client_id, link.capsule_id).get(currency, 0)
        funded = sum(claims[link.capsule_id] * link.share_bp // 10000 for link in own)
        remaining = max(0, (event.target_amount_minor or 0) - funded - planned.get(event.id, 0))
        monthly = Money(remaining // max(1, months), currency)
        planned[event.id] = planned.get(event.id, 0) + monthly.minor
        for link, part in zip(own, monthly.allocate([link.share_bp for link in own])):
            amounts[link.capsule_id] = amounts.get(link.capsule_id, 0) + part.minor
    return amounts


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


def plan(db: Session, client_id: int, start: str, end: str, plan_id: int | None) -> dict:
    goal = _goal(db, client_id)
    periods = _periods(start, end)
    currency = money_client_currency(db, client_id)
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=goal.id).all()
    names = {account.id: account.name for account in db.query(models.Account).filter_by(client_id=client_id).all()}
    capsules = {capsule.id: capsule for capsule in db.query(models.Capsule).filter_by(client_id=client_id).all()}
    stored = [line for line in active_lines_for_periods(db, client_id, plan_id, periods) if line.source_kind == GOAL_SOURCE]
    # Earmarks linked to the goal's events get their rows from the goal, whatever the month.
    tracked = {link.capsule_id for link in db.query(models.GoalEventEarmark).join(models.LifeEvent).filter(
        models.GoalEventEarmark.client_id == client_id, models.LifeEvent.scenario_id == goal.id)}
    claims: dict[int, int] = {}
    planned: dict[int, int] = {}
    changes, months = [], []
    warned: dict[str, list[str]] = {}
    for period in periods:
        wanted: dict[tuple, int] = {}
        taken: dict[int, int] = {}
        for capsule_id, minor in _earmark_minor(db, client_id, goal, period, currency, claims, planned).items():
            capsule = capsules.get(capsule_id)
            if capsule is None:
                continue
            for account_id, part in capsule_shares(capsule, Money(minor, currency)):
                wanted[("capsule", capsule_id, account_id)] = part.minor
                if account_id is None:
                    warned.setdefault(f"取り置き「{capsule.name}」に資金元の口座がありません。", []).append(period)
                else:
                    taken[account_id] = taken.get(account_id, 0) + part.minor
        contribution_total = 0
        other = _other_allocations(db, client_id, period, plan_id, tracked, currency)
        for account_id in sorted({plan.account_id for plan in plans}):
            contribution = resolve(plans, account_id, period, goal.annual_return)[0]
            contribution_total += contribution
            used = taken.get(account_id, 0) + other.get(account_id, 0)
            if used > contribution:
                warned.setdefault(f"「{names.get(account_id, account_id)}」は取り置きと既存の配分（自動取引など）が積立設定の月額を超えています。", []).append(period)
            if contribution:
                wanted[("account", None, account_id)] = max(0, contribution - used)
        rows = {(("capsule", line.target_id, line.account_id) if line.target_type == "capsule" else ("account", None, line.account_id)): line
                for line in stored if line.target_period == period}
        for key in sorted(set(wanted) | set(rows), key=lambda item: (item[0], item[1] or 0, item[2] or 0)):
            kind, capsule_id, account_id = key
            line = rows.get(key)
            current = line.amount_minor if line is not None else 0
            new = wanted.get(key, 0)
            if line is None and new == 0:
                continue
            changes.append({
                "period": period, "kind": kind, "account_id": account_id, "account_name": names.get(account_id),
                "capsule_id": capsule_id, "capsule_name": capsules[capsule_id].name if capsule_id in capsules else None,
                "line_id": line.id if line is not None else None,
                "current": Money(current, currency).to_float(), "new": Money(new, currency).to_float(),
                "current_minor": current, "new_minor": new, "changed": line is None or current != new or key not in wanted,
                "retire": key not in wanted,
            })
        months.append({"period": period, "contribution": Money(contribution_total, currency).to_float(),
                       "earmarks": Money(sum(minor for key, minor in wanted.items() if key[0] == "capsule"), currency).to_float()})
    basis = {"scenario_id": goal.id, "periods": periods,
             "changes": [{key: change[key] for key in ("period", "kind", "account_id", "capsule_id", "line_id", "current_minor", "new_minor", "retire")}
                         for change in changes]}
    fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
    return {"scenario": {"id": goal.id, "name": goal.name}, "periods": periods, "currency": currency,
            "months": months, "changes": changes, "warnings": [_warning(message, sorted(set(when))) for message, when in warned.items()],
            "fingerprint": fingerprint}


def plan_check(db: Session, client_id: int, period: str) -> dict:
    """Per account: what the goal's 積立設定 puts aside this month, and what the plan does."""
    goal = get_goal(db, client_id)
    currency = money_client_currency(db, client_id)
    if goal is None:
        return {"period": period, "goal": None, "accounts": [], "contribution": 0.0, "planned": 0.0, "difference": 0.0}
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=goal.id).all()
    planned: dict[int, float] = {}
    for line in month_plan_lines(db, client_id, period):
        if line.get("line_type") != "allocation" or not line.get("account_id"):
            continue
        if line.get("target_type") in {"account", "capsule"}:
            planned[line["account_id"]] = planned.get(line["account_id"], 0.0) + float(line.get("budget_amount") or 0.0)
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
