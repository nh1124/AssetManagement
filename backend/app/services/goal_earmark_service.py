"""Goal progress: what the earmark made for each goal event holds, and what it still needs."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from .capsule_service import claimed_minor, goal_capsules
from .contribution_plan_service import event_withdrawals
from .life_scenario_scope import get_goal
from .money_storage import money_client_currency


def funded(db: Session, client_id: int, event_ids) -> dict[int, float]:
    """An event's 確保額: the client-currency claim of the earmark made for it."""
    currency = money_client_currency(db, client_id)
    return {event_id: Money(claimed_minor(db, client_id, capsule.id).get(currency, 0), currency).to_float()
            for event_id, capsule in goal_capsules(db, client_id, event_ids).items()}


def _months_until(today: date, target: date | None) -> int:
    if target is None:
        return 0
    return max(0, (target.year - today.year) * 12 + target.month - today.month)


def events_with_progress(db: Session, client_id: int, scenario_id: int | None = None,
                         *, reference_date: date | None = None) -> list[dict]:
    """The goal scenario's events (or another scenario's) with the funding their earmarks give."""
    scenario = get_goal(db, client_id) if scenario_id is None else db.query(models.LifeScenario).filter_by(
        client_id=client_id, id=scenario_id).first()
    if scenario is None:
        return []
    today = reference_date or date.today()
    events = db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=scenario.id).order_by(
        models.LifeEvent.target_date, models.LifeEvent.id).all()
    ids = [event.id for event in events]
    progress = funded(db, client_id, ids)
    capsules = goal_capsules(db, client_id, ids)
    taken = event_withdrawals(db, ids)
    currency = money_client_currency(db, client_id)
    rows = []
    for event in events:
        target = float(event.target_amount or 0.0)
        expense = event.direction == "expense"
        current = progress.get(event.id, 0.0) if expense else 0.0
        capsule = capsules.get(event.id)
        rows.append({
            "id": event.id, "scenario_id": event.scenario_id, "lineage": event.lineage, "name": event.name,
            "direction": event.direction, "target_date": event.target_date,
            "withdrawals": [{"account_id": row.account_id, "account_name": row.account.name if row.account else None, "period": row.start_period,
                             "amount": Money(row.amount_minor, currency).to_float(), "interval_months": row.interval_months,
                             "repeat_count": row.repeat_count, "end_period": row.end_period} for row in taken.get(event.id, [])],
            "target_amount": target, "priority": event.priority, "note": event.note,
            "condition_mode": event.condition_mode, "interest_rate": event.interest_rate,
            "borrowing_event_id": event.borrowing_event_id, "repeat_count": event.repeat_count,
            "current_funded": current, "gap": max(0.0, target - current) if expense else 0.0,
            "progress_percentage": round(min(100.0, current / target * 100), 1) if target > 0 and expense else 0.0,
            "months_remaining": _months_until(today, event.target_date),
            "earmark": {"capsule_id": capsule.id, "capsule_name": capsule.name} if capsule is not None else None,
        })
    return rows


def funding_gap(db: Session, client_id: int) -> dict:
    """What the goal still needs, and the monthly pace that would close it by each target date."""
    events = [row for row in events_with_progress(db, client_id) if row["direction"] == "expense"]
    gap = sum(row["gap"] for row in events)
    monthly = sum(row["gap"] / max(1, row["months_remaining"]) for row in events)
    return {"goals_count": len(events), "total_goal_gap": round(gap, 0), "required_monthly_savings": round(monthly, 0)}
