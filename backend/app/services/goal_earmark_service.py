"""Own 実績管理の設定: which earmarks count toward each goal event, and the progress they give."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import NotFound, Refused
from ..domain.money import Money
from .capsule_service import claimed_minor
from .goal_service import get_life_event
from .life_scenario_scope import get_goal
from .money_storage import money_client_currency


def links(db: Session, client_id: int, event_ids) -> dict[int, list[dict]]:
    """{event_id: [{capsule_id, capsule_name, share}]}, share in percent."""
    rows = db.query(models.GoalEventEarmark, models.Capsule.name).join(
        models.Capsule, models.Capsule.id == models.GoalEventEarmark.capsule_id,
    ).filter(models.GoalEventEarmark.client_id == client_id,
             models.GoalEventEarmark.life_event_id.in_(list(event_ids))).order_by(models.GoalEventEarmark.id).all()
    result: dict[int, list[dict]] = {}
    for link, name in rows:
        result.setdefault(link.life_event_id, []).append(
            {"capsule_id": link.capsule_id, "capsule_name": name, "share": link.share_bp / 100})
    return result


def replace_links(db: Session, client_id: int, event_id: int, rows: list[dict]) -> None:
    event = get_life_event(db, client_id, event_id)
    if event is None:
        raise NotFound("ライフイベントが見つかりません。")
    if event.direction != "expense" and rows:
        raise Refused("収入のイベントには取り置きを紐づけません。", status_code=422)
    capsule_ids = [row["capsule_id"] for row in rows]
    if len(set(capsule_ids)) != len(capsule_ids):
        raise Refused("同じ取り置きを重ねて選べません。", status_code=422)
    found = {capsule.id for capsule in db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id, models.Capsule.id.in_(capsule_ids)).all()}
    if found != set(capsule_ids):
        raise NotFound("同じクライアントの取り置きを選択してください。")
    shares = []
    for row in rows:
        share = row.get("share", 100)
        if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 <= share <= 100:
            raise Refused("割合は0〜100％で指定してください。", status_code=422)
        shares.append(round(share * 100))
    db.query(models.GoalEventEarmark).filter_by(client_id=client_id, life_event_id=event_id).delete(synchronize_session="fetch")
    for capsule_id, share_bp in zip(capsule_ids, shares):
        db.add(models.GoalEventEarmark(client_id=client_id, life_event_id=event_id, capsule_id=capsule_id, share_bp=share_bp))
    db.commit()


def funded(db: Session, client_id: int, event_ids) -> dict[int, float]:
    """An event's 確保額: the client-currency claim of each linked earmark times its share."""
    currency = money_client_currency(db, client_id)
    claims: dict[int, int] = {}
    totals: dict[int, int] = {}
    for link in db.query(models.GoalEventEarmark).filter(
        models.GoalEventEarmark.client_id == client_id, models.GoalEventEarmark.life_event_id.in_(list(event_ids)),
    ).all():
        if link.capsule_id not in claims:
            claims[link.capsule_id] = claimed_minor(db, client_id, link.capsule_id).get(currency, 0)
        totals[link.life_event_id] = totals.get(link.life_event_id, 0) + claims[link.capsule_id] * link.share_bp // 10000
    return {event_id: Money(minor, currency).to_float() for event_id, minor in totals.items()}


def _months_until(today: date, target: date | None) -> int:
    if target is None:
        return 0
    return max(0, (target.year - today.year) * 12 + target.month - today.month)


def events_with_progress(db: Session, client_id: int, scenario_id: int | None = None,
                         *, reference_date: date | None = None) -> list[dict]:
    """The goal scenario's events (or another scenario's) with their funding progress."""
    scenario = get_goal(db, client_id) if scenario_id is None else db.query(models.LifeScenario).filter_by(
        client_id=client_id, id=scenario_id).first()
    if scenario is None:
        return []
    today = reference_date or date.today()
    events = db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=scenario.id).order_by(
        models.LifeEvent.target_date, models.LifeEvent.id).all()
    progress = funded(db, client_id, [event.id for event in events])
    attached = links(db, client_id, [event.id for event in events])
    rows = []
    for event in events:
        target = float(event.target_amount or 0.0)
        current = progress.get(event.id, 0.0) if event.direction == "expense" else 0.0
        rows.append({
            "id": event.id, "scenario_id": event.scenario_id, "lineage": event.lineage, "name": event.name,
            "direction": event.direction, "account_id": event.account_id, "target_date": event.target_date,
            "target_amount": target, "priority": event.priority, "note": event.note,
            "condition_mode": event.condition_mode,
            "current_funded": current, "gap": max(0.0, target - current) if event.direction == "expense" else 0.0,
            "progress_percentage": round(min(100.0, current / target * 100), 1) if target > 0 and event.direction == "expense" else 0.0,
            "months_remaining": _months_until(today, event.target_date),
            "earmarks": attached.get(event.id, []),
        })
    return rows


def funding_gap(db: Session, client_id: int) -> dict:
    """What the goal still needs, and the monthly pace that would close it by each target date."""
    events = [row for row in events_with_progress(db, client_id) if row["direction"] == "expense"]
    gap = sum(row["gap"] for row in events)
    monthly = sum(row["gap"] / max(1, row["months_remaining"]) for row in events)
    return {"goals_count": len(events), "total_goal_gap": round(gap, 0), "required_monthly_savings": round(monthly, 0)}
