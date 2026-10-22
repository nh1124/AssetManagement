"""Compute the plan the goal asks for, from its 積立設定 and its events' earmark settings.

For every month of the range:
- each goal expense event with ライフイベントへの取り崩し records gets an earmark row per
  account: the rest of what the records take from that account over their whole schedule
  (up to the event's amount; − what the earmark holds there − what earlier months of the
  range already plan), spread evenly over the months left to the account's first
  withdrawal (R8). The earmark is the one made for the event (capsules.goal_event_id);
  apply creates it, named after the event, with a funding source per account;
- each month a withdrawal record moves money in gets a withdrawal row (取り崩し) for its account;
- each account with 積立 records gets an allocation row: what they put in that month
  less what the plan already transfers into it (automatic transfers, rows typed by hand),
  so what reaches the account comes to the 積立設定 (R7). Earmarks set part of the
  account's money aside and are not taken off it as well (R3: they are its breakdown).
  Warnings say when the transfers, or the earmarks, already come to more;
- each 口座振替 in the month gets an allocation row into its destination with its source
  account (ゴールの振替).
Only rows the goal wrote before (source "goal") are replaced; rows typed by hand stay.
Nothing changes until the user confirms the exact preview: apply recomputes it and
refuses when the fingerprint differs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Refused
from ..domain.money import Money
from . import goal_budget_record
from .budget_lines import earmark_counted_shares
from .budget_plan_service import month_plan_lines
from .budget_plan_store import active_lines_for_periods
from .capsule_service import claimed_value_minor, goal_capsules
from .client_settings_service import client_language, pick, reflection_settings
from .contribution_plan_service import (
    contributed_minor, event_withdrawals, moved_minor, of_kind, occurrence_indexes, period_index, total_minor, withdrawals,
)
from .goal_service import list_goals
from .life_scenario_scope import get_goal
from .money_storage import money_client_currency

GOAL_SOURCE = "goal"
REFLECTION_NOTIFICATION = "goal_reflection"
GOAL_LINE_NAME = "ゴールの積立"
GOAL_DRAWDOWN_NAME = "ゴールの取り崩し"
GOAL_TRANSFER_NAME = "ゴールの振替"
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
    """{event_id: {account_id: (minor, first month)}}: what each account withdraws for each event over the
    records' whole schedules (no more than the event's amount), and from when."""
    amounts = {event.id: event.target_amount_minor or 0 for event in events}
    schedule: dict[int, dict[int, tuple[int, str]]] = {}
    for event_id, records in event_withdrawals(db, list(amounts)).items():
        totals: dict[int, tuple[int, str]] = {}
        for record in records:
            minor, first = totals.get(record.account_id, (0, record.start_period))
            totals[record.account_id] = (minor + total_minor(record), min(first, record.start_period))
        # The event's amount is shared out in the order the accounts first withdraw.
        left = amounts[event_id]
        schedule[event_id] = {}
        for account_id, (minor, first) in sorted(totals.items(), key=lambda item: (item[1][1], item[0])):
            part = min(minor, max(0, left))
            left -= part
            schedule[event_id][account_id] = (part, first)
    return schedule


def earmark_parts(db: Session, events: list[models.LifeEvent]) -> dict[int, dict[int, int]]:
    """{event_id: {account_id: minor}}: the earmark's target per account, what the records withdraw."""
    return {event_id: {account_id: minor for account_id, (minor, _) in accounts.items()}
            for event_id, accounts in earmark_schedule(db, events).items()}


def _other_allocations(db: Session, client_id: int, period: str, plan_id: int | None, tracked: set[int],
                       currency: str) -> tuple[dict[int, int], dict[int, int]]:
    """({account_id: minor} transferred into each account, {account_id: minor} earmarked in it) by the
    month's plan apart from the goal's own rows."""
    transfers: dict[int, int] = {}
    earmarks: dict[int, int] = {}
    for line in month_plan_lines(db, client_id, period, plan_id):
        if line.get("line_type") != "allocation" or not line.get("account_id") or GOAL_SOURCE in (line.get("source"), line.get("source_kind")):
            continue
        if line.get("target_type") == "capsule" and line.get("target_id") in tracked:
            continue
        bucket = earmarks if line.get("target_type") == "capsule" else transfers if line.get("target_type") == "account" else None
        if bucket is not None:
            bucket[line["account_id"]] = bucket.get(line["account_id"], 0) + Money.from_major(str(line.get("budget_amount") or 0), currency).minor
    return transfers, earmarks


def _amount_text(minor: int, currency: str) -> str:
    value = Money(minor, currency).to_float()
    return f"¥{value:,.0f}" if currency == "JPY" else f"{value:,.2f} {currency}"


def _warning(message: str, periods: list[str], language: str = "ja") -> str:
    if len(periods) == 1:
        return pick(language, f"{periods[0]}：{message}", f"{periods[0]}: {message}")
    return pick(language, f"{periods[0]}〜{periods[-1]}のうち{len(periods)}か月：{message}",
                f"{len(periods)} months from {periods[0]} to {periods[-1]}: {message}")


def _stored_key(line: models.MonthlyPlanLine) -> tuple[str, str, int | None]:
    if line.target_type == "capsule":
        return "capsule", str(line.target_id), line.account_id
    if line.line_type == "drawdown":
        return "drawdown", "", line.account_id
    # A transfer row names where the money comes from; the 積立 row does not.
    if line.source_account_id:
        return "transfer", str(line.source_account_id), line.account_id
    return "account", "", line.account_id


DEFAULT_OPTIONS = {"base": "remaining", "held": "even", "catch_up": "even", "since": None}


def _spread(total: int, months: int) -> list[int]:
    """total over `months` months, the remainder in the later months (as the plan always split it)."""
    rows, left = [], total
    for index in range(months):
        part = left // (months - index)
        rows.append(part)
        left -= part
    return rows


def _take_off(rows: list[int], amount: int, held: str) -> list[int]:
    """rows less `amount`: from the nearest months first (recent) or the same each month (even), never below 0."""
    if amount <= 0 or not rows:
        return rows
    if held == "recent":
        result = []
        for row in rows:
            taken = min(row, amount)
            amount -= taken
            result.append(row - taken)
        return result
    return [max(0, row - part) for row, part in zip(rows, _spread(amount, len(rows)))]


def _add_on(rows: list[int], amount: int, catch_up: str) -> list[int]:
    """rows plus a shortfall: on the first month (recent), the same on every month (even), or not at all (none)."""
    if amount <= 0 or catch_up == "none" or not rows:
        return rows
    if catch_up == "recent":
        return [rows[0] + amount, *rows[1:]]
    return [row + part for row, part in zip(rows, _spread(amount, len(rows)))]


def earmark_rows(target: int, held: int, first: int, current: int, started: int, options: dict) -> list[int]:
    """One earmark part's rows from `current` up to the month before `first`.

    remaining (残り期間に合わせる): the target over the months left, less what the earmark holds (evenly, or
    from the nearest months). goal_setting (積立設定から決まる額): the target over the months from the earmark's
    start, fixed; what it holds beyond that schedule comes off the same two ways, and a shortfall is caught up
    as catch_up says. In the withdrawal month itself the rest is planned at once.
    """
    left = first - current
    if left <= 0:
        return [max(0, target - held)] if left == 0 else []
    if options["base"] == "goal_setting":
        whole = max(left, first - started)
        schedule = _spread(target, whole)
        elapsed = whole - left
        rows, expected = schedule[elapsed:], sum(schedule[:elapsed])
        if held >= expected:
            return _take_off(rows, held - expected, options["held"])
        return _add_on(rows, expected - held, options["catch_up"])
    return _take_off(_spread(target, left), held, options["held"])


def account_movement_minor(db: Session, client_id: int, account_id: int, period: str) -> int:
    """What came into an account in a month, net of what left it, in the client's currency (journal legs)."""
    first, last = _index(period), _index(period) + 1
    start, stop = date(first // 12, first % 12 + 1, 1), date(last // 12, last % 12 + 1, 1)
    currency = money_client_currency(db, client_id)
    value = db.query(func.coalesce(func.sum(models.JournalEntry.debit_minor - models.JournalEntry.credit_minor), 0)).join(
        models.Transaction, models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(
        models.Transaction.client_id == client_id, models.JournalEntry.account_id == account_id,
        models.Transaction.date >= start, models.Transaction.date < stop, models.Transaction.currency == currency,
    ).scalar()
    return int(value or 0)


def contribution_shortfalls(db: Session, client_id: int, plans, account_ids, since: str | None, current: str) -> dict[int, int]:
    """{account_id: how far the account fell behind its 積立設定} from `since` to the month before `current`:
    what the records bring in (積立 + transfers in − withdrawals) less what actually came in, when positive."""
    if not since or since >= current:
        return {}
    months = [_period(index) for index in range(_index(since), _index(current))]
    found = {}
    for account_id in account_ids:
        expected = sum(expected_minor(plans, account_id, month) for month in months)
        actual = sum(account_movement_minor(db, client_id, account_id, month) for month in months)
        if expected > actual:
            found[account_id] = expected - actual
    return found


def plan(db: Session, client_id: int, start: str, end: str, plan_id: int | None, options: dict | None = None) -> dict:
    """The rows the goal asks for in [start, end]. options: 基準 base (remaining / goal_setting), 確保済みの引き方 held
    (even / recent), 遅れの取り返し catch_up (even / recent / none) and since, the first month a 積立 shortfall counts."""
    options = {**DEFAULT_OPTIONS, **(options or {})}
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
    claims = {(event.id, account_id): claimed_value_minor(db, client_id, existing[event.id].id, account_id)
              if event.id in existing else 0
              for event in events for account_id in schedule[event.id]}
    taken_out = withdrawals(plans)
    stored = [line for line in active_lines_for_periods(db, client_id, plan_id, periods) if line.source_kind == GOAL_SOURCE]
    opening = _index(periods[0])
    # Each earmark part's rows from this month to the month before its first withdrawal, made once (R8, WP27).
    earmark_plan: dict[tuple[int, int], list[int]] = {}
    for event in events:
        capsule = existing.get(event.id)
        started = (capsule.created_at.year * 12 + capsule.created_at.month - 1) if capsule is not None and capsule.created_at else opening
        for account_id, (target, first) in schedule[event.id].items():
            earmark_plan[(event.id, account_id)] = earmark_rows(target, claims[(event.id, account_id)], _index(first), opening, started, options)
    contributors = sorted({record.account_id for record in of_kind(plans, "contribution")})
    caught_up = {account_id: _add_on([0] * len(periods), shortfall, options["catch_up"])
                 for account_id, shortfall in contribution_shortfalls(db, client_id, plans, contributors, options["since"], periods[0]).items()}
    changes, months = [], []
    warned: dict[str, list[str]] = {}
    language = client_language(db, client_id)
    for period in periods:
        wanted: dict[tuple[str, str, int | None], int] = {}
        made_for: dict[tuple[str, str, int | None], models.LifeEvent] = {}
        taken: dict[int, int] = {}
        for event in events:
            capsule = existing.get(event.id)
            for account_id in schedule[event.id]:
                rows = earmark_plan[(event.id, account_id)]
                offset = _index(period) - opening
                if offset >= len(rows):
                    continue
                monthly = rows[offset]
                key = ("capsule", str(capsule.id) if capsule is not None else f"event:{event.id}", account_id)
                wanted[key] = monthly
                made_for[key] = event
                taken[account_id] = taken.get(account_id, 0) + monthly
        contribution_total = 0
        month = period_index(period)
        for record in taken_out:
            if occurrence_indexes(record, month, month):
                key = ("drawdown", "", record.account_id)
                wanted[key] = wanted.get(key, 0) + record.amount_minor
        for record in of_kind(plans, "transfer"):
            if occurrence_indexes(record, month, month):
                key = ("transfer", str(record.account_id), record.to_account_id)
                wanted[key] = wanted.get(key, 0) + record.amount_minor
        transfers, held = _other_allocations(db, client_id, period, plan_id, tracked, currency)
        for account_id in contributors:
            contribution = contributed_minor(plans, account_id, period)
            extra = caught_up.get(account_id, [0] * len(periods))[_index(period) - opening]
            contribution_total += contribution
            name, monthly = names.get(account_id, account_id), _amount_text(contribution, currency)
            moved = transfers.get(account_id, 0)
            if moved > contribution:
                warned.setdefault(pick(language, f"「{name}」は既存の振替（自動取引など）{_amount_text(moved, currency)}が積立設定の月額{monthly}を超えています。",
                                       f"“{name}”: existing transfers (such as automatic transactions) of {_amount_text(moved, currency)} exceed the monthly contribution of {monthly}."), []).append(period)
            set_aside = taken.get(account_id, 0) + held.get(account_id, 0)
            if set_aside > contribution:
                warned.setdefault(pick(language, f"「{name}」は取り置き{_amount_text(set_aside, currency)}が積立設定の月額{monthly}を超えています（超える分は口座の残高から確保します）。",
                                       f"“{name}”: earmarks of {_amount_text(set_aside, currency)} exceed the monthly contribution of {monthly} (the rest is set aside from the account balance)."), []).append(period)
            if contribution or extra:
                # A shortfall of earlier months comes on top, as the settings say (WP27).
                wanted[("account", "", account_id)] = max(0, contribution - moved) + extra
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
            source_id = int(target) if kind == "transfer" else None
            changes.append({
                "period": period, "kind": kind, "account_id": account_id, "account_name": names.get(account_id),
                "source_account_id": source_id, "source_account_name": names.get(source_id) if source_id else None,
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
    basis = {"scenario_id": goal.id, "periods": periods, "options": {key: options[key] for key in ("base", "held", "catch_up")},
             "changes": [{key: change[key] for key in ("period", "kind", "account_id", "source_account_id", "capsule_id", "event_id", "line_id",
                                                       "current_minor", "new_minor", "retire")}
                         for change in changes]}
    fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
    return {"scenario": {"id": goal.id, "name": goal.name}, "periods": periods, "currency": currency,
            "months": months, "changes": changes, "warnings": [_warning(message, sorted(set(when)), language) for message, when in warned.items()],
            "fingerprint": fingerprint}


def expected_minor(plans, account_id: int, period: str) -> int:
    """What the 積立設定 brings into an account in a month: its 積立 and the transfers into it, less its withdrawals.
    A transfer out is not taken off the source: the plan writes it on the destination, naming the source."""
    return (contributed_minor(plans, account_id, period) + moved_minor(plans, "transfer", period, to_account_id=account_id)
            - moved_minor(plans, "withdrawal", period, account_id=account_id))


def plan_check(db: Session, client_id: int, period: str) -> dict:
    """Per account: what the goal's 積立設定 brings in (or withdraws) this month, and what the plan does."""
    goal = get_goal(db, client_id)
    currency = money_client_currency(db, client_id)
    if goal is None:
        return {"period": period, "goal": None, "accounts": [], "contribution": 0.0, "planned": 0.0, "difference": 0.0}
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=goal.id).all()
    planned: dict[int, float] = {}
    lines = [line for line in month_plan_lines(db, client_id, period)
             if line.get("account_id") and line.get("target_type") in {"account", "capsule"}]
    # Earmarks count only beyond the transfers into their account, as the plan summary counts them.
    shares = earmark_counted_shares(lines, lambda line: line.get("budget_amount"))
    for line in lines:
        sign = 1 if line.get("line_type") == "allocation" else -1 if line.get("line_type") == "drawdown" else 0
        if sign:
            amount = float(line.get("budget_amount") or 0.0)
            if line.get("line_type") == "allocation" and line.get("target_type") == "capsule":
                amount *= shares.get(line["account_id"], 1.0)
            planned[line["account_id"]] = planned.get(line["account_id"], 0.0) + sign * amount
    accounts = {account.id: account for account in db.query(models.Account).filter_by(client_id=client_id, account_type="asset").all()}
    rows = []
    named = {plan.account_id for plan in plans} | {plan.to_account_id for plan in plans if plan.to_account_id}
    for account_id in sorted(set(planned) | named):
        if account_id not in accounts:
            continue
        contribution = Money(expected_minor(plans, account_id, period), currency).to_float()
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
    """One reminder while the goal sets money aside and no reflection covers this month (自動反映 off only)."""
    goal = get_goal(db, client_id)
    if goal is None or goal_budget_record.covering(db, client_id, period) is not None:
        return []
    client = db.query(models.Client).filter_by(id=client_id).first()
    if client is not None and reflection_settings(client)["enabled"]:
        return []
    plans = db.query(models.ScenarioContributionPlan).filter_by(scenario_id=goal.id).all()
    if not (moved_minor(plans, "contribution", period) or moved_minor(plans, "transfer", period)):
        return []
    language = client_language(db, client_id)
    return [{
        "dedupe_key": f"{REFLECTION_NOTIFICATION}:{goal.id}:{period}",
        "title": pick(language, "計画への反映がまだです", "The plan is not reflected yet"),
        "body": pick(language,
                     f"{period} の計画にゴール「{goal.name}」の積立設定がまだ反映されていません。計画の ⚙ から「今すぐ反映」するか、自動反映をオンにしてください。",
                     f"The contribution settings of the goal “{goal.name}” are not in the plan for {period} yet. Use “Reflect now” from the plan’s ⚙, or turn on automatic reflection."),
        "payload": {"period": period, "scenario_id": goal.id},
        "link": "/plan",
    }]
