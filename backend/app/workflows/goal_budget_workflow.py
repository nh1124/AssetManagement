"""Write the plan the goal asks for, after the user confirmed the exact preview.

The computation is goal_plan_service's; apply recomputes it and refuses when the
fingerprint differs, so a change between preview and apply is shown again.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..domain.errors import Conflict
from ..services import capsule_service, goal_budget_record, notification_service
from ..services.budget_plan_store import (
    create_plan_lines,
    find_budget_plan_id,
    resolve_budget_plan_id,
    retire_plan_lines,
    update_plan_lines,
)
from ..services.cache_service import invalidate_client
from ..services.goal_plan_service import GOAL_DRAWDOWN_NAME, GOAL_LINE_NAME, GOAL_SOURCE, REFLECTION_NOTIFICATION, earmarked_events, plan
from ..services.life_scenario_scope import get_goal, lock_client


def preview(db: Session, client_id: int, start_period: str, end_period: str) -> dict:
    """Everything making the plan would write; nothing is saved."""
    return plan(db, client_id, start_period, end_period, find_budget_plan_id(db, client_id))


def apply(db: Session, client_id: int, start_period: str, end_period: str, fingerprint: str) -> dict:
    lock_client(db, client_id)
    try:
        existing_plan = find_budget_plan_id(db, client_id)
        planned = plan(db, client_id, start_period, end_period, existing_plan)
        if planned["fingerprint"] != fingerprint:
            raise Conflict("ゴールか計画の内容が確認後に変わりました。もう一度確認してください。")
        plan_id = existing_plan if existing_plan is not None else resolve_budget_plan_id(db, client_id, commit=False)
        changed = [change for change in planned["changes"] if change["changed"]]
        # The earmark an event is planned into is made once, named after the event, in its account.
        made: dict[int, int] = {}
        events = {event.id: event for event in earmarked_events(db, client_id, get_goal(db, client_id))}
        for change in planned["changes"]:
            if change["new_capsule"] and not change["retire"] and change["event_id"] not in made:
                event = events[change["event_id"]]
                made[event.id] = capsule_service.create_goal_capsule(
                    db, client_id, event_id=event.id, name=event.name, target_minor=event.target_amount_minor or 0,
                    account_id=event.account_id, monthly_minor=change["new_minor"],
                ).id
            elif change["kind"] == "capsule" and change["capsule_id"] and change["period"] == planned["periods"][0] and not change["retire"]:
                capsule_service.set_goal_capsule_monthly(db, client_id, change["capsule_id"], change["new_minor"])
        retires = [change["line_id"] for change in changed if change["retire"] and change["line_id"] is not None]
        updates = [{"id": change["line_id"], "amount": change["new"], "manual_override": False}
                   for change in changed if not change["retire"] and change["line_id"] is not None]
        creates = []
        for change in changed:
            if change["retire"] or change["line_id"] is not None:
                continue
            row = {"plan_id": plan_id, "target_period": change["period"], "line_type": "allocation",
                   "account_id": change["account_id"], "amount": change["new"], "source": GOAL_SOURCE,
                   "source_kind": GOAL_SOURCE, "cash_treatment": "auto"}
            if change["kind"] == "capsule":
                row.update(target_type="capsule", target_id=change["capsule_id"] or made[change["event_id"]])
            elif change["kind"] == "drawdown":
                row.update(line_type="drawdown", target_type="account", name=GOAL_DRAWDOWN_NAME)
            else:
                row.update(target_type="account", name=GOAL_LINE_NAME)
            creates.append(row)
        try:
            # Retire first so a replacement row never meets the row it replaces.
            if retires:
                retire_plan_lines(db, client_id, retires, commit=False)
            if updates:
                update_plan_lines(db, client_id, updates, commit=False)
            if creates:
                create_plan_lines(db, client_id, creates, commit=False)
        except ValueError as exc:
            raise Conflict(f"計画の行を書き込めませんでした：{exc}") from exc
        goal_budget_record.record(db, client_id, scenario_id=planned["scenario"]["id"], start_period=planned["periods"][0],
                                  end_period=planned["periods"][-1], summary={"months": planned["months"], "changes": len(changed)})
        # A confirmed reflection answers the notification that asked for it.
        notification_service.resolve_kind(db, client_id, REFLECTION_NOTIFICATION)
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return {"applied": len(changed), "periods": planned["periods"], "currency": planned["currency"]}


