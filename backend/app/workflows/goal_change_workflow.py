"""Change the goal, and decide what happens to the old goal's earmarks (R11).

- keep: the earmarks stay as they are (they no longer count as the goal's);
- replace: they are deleted, their claims go back to their accounts, the old goal's
  plan rows from this month on are retired, and an earmark is made for each new goal
  expense event with a 資金の割り当て;
- carry: each one moves to the event of the new goal with the same lineage (the same
  event in a copied scenario), keeping what it holds; the rest stay as they are.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from ..services import capsule_service, life_scenario_service
from ..services.budget_plan_store import lines_written_by, retire_plan_lines
from ..services.cache_service import invalidate_client
from ..services.goal_plan_service import GOAL_SOURCE, earmark_parts, earmarked_events
from ..services.goal_service import list_goals
from ..services.ledger_service import list_accounts
from ..services.life_scenario_scope import get, get_goal, lock_client


def _situation(db: Session, client_id: int, scenario_id: int) -> dict:
    scenario = get(db, client_id, scenario_id)
    previous = get_goal(db, client_id)
    old_events = list_goals(db, client_id, previous.id) if previous is not None and previous.id != scenario.id else []
    new_events = list_goals(db, client_id, scenario.id)
    capsules = capsule_service.goal_capsules(db, client_id, [event.id for event in old_events])
    by_lineage = {event.lineage: event for event in new_events}
    return {"scenario": scenario, "previous": previous, "old_events": {event.id: event for event in old_events},
            "capsules": capsules, "by_lineage": by_lineage}


def preview(db: Session, client_id: int, scenario_id: int) -> dict:
    """What each choice would touch: the old goal's earmarks, and the earmarks the new goal would get."""
    found = _situation(db, client_id, scenario_id)
    names = {account.id: account.name for account in list_accounts(db, client_id, account_type="asset", ordered=False)}
    made = capsule_service.goal_capsules(db, client_id, [event.id for event in found["by_lineage"].values()])
    rows = []
    for event_id, capsule in found["capsules"].items():
        target = found["by_lineage"].get(found["old_events"][event_id].lineage)
        rows.append({"capsule_id": capsule.id, "capsule_name": capsule.name, "event_name": found["old_events"][event_id].name,
                     "claim": capsule_service.claimed_value(db, client_id, capsule.id),
                     "carry_to": target.name if target is not None else None})
    events = [event for event in earmarked_events(db, client_id, found["scenario"]) if event.id not in made]
    targets = earmark_parts(db, events)
    create = [{"event_id": event.id, "name": event.name, "account_name": "・".join(names.get(account_id, str(account_id)) for account_id in targets[event.id])}
              for event in events]
    previous = found["previous"]
    return {"scenario": {"id": found["scenario"].id, "name": found["scenario"].name},
            "current_goal": {"id": previous.id, "name": previous.name} if previous is not None else None,
            "capsules": rows, "create": create}


def apply(db: Session, client_id: int, scenario_id: int, earmarks: str) -> models.LifeScenario:
    lock_client(db, client_id)
    try:
        found = _situation(db, client_id, scenario_id)
        scenario = life_scenario_service.make_goal(db, client_id, scenario_id, commit=False)
        if earmarks == "carry":
            for event_id, capsule in found["capsules"].items():
                target = found["by_lineage"].get(found["old_events"][event_id].lineage)
                if target is not None:
                    capsule_service.relink_goal_capsule(db, client_id, capsule.id, target.id)
        elif earmarks == "replace":
            old_ids = [capsule.id for capsule in found["capsules"].values()]
            stale = lines_written_by(db, client_id, GOAL_SOURCE, from_period=date.today().strftime("%Y-%m"), capsule_ids=old_ids)
            if stale:
                retire_plan_lines(db, client_id, [line.id for line in stale], commit=False)
            for capsule_id in old_ids:
                capsule_service.delete_capsule(db, client_id, capsule_id, commit=False)
            made = capsule_service.goal_capsules(db, client_id, [event.id for event in found["by_lineage"].values()])
            events = [event for event in earmarked_events(db, client_id, scenario) if event.id not in made]
            targets = earmark_parts(db, events)
            for event in events:
                capsule_service.create_goal_capsule(db, client_id, event_id=event.id, name=event.name,
                                                    parts=targets[event.id])
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return scenario
