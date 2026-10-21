"""計画への反映 (WP27): write the goal and the product earmarks into the plan, by itself or when asked.

With 自動反映 on, a run happens at the start of a month (the daily loop and sign-in) and after a change of
what the plan is made from (the goal's 積立設定 and events, earmarks, products, automatic transactions, the
user's records, the settings); 今すぐ反映 runs it on request. A run rewrites this month and the 11 after it:
the goal's rows (goal_plan_service, with the settings' 基準・確保済みの引き方・遅れの取り返し) and the rows of
earmarks with linked products (product_reserve_plan). Past months are never touched; the user's records are
never replaced (product earmarks' rows in the range are, whatever wrote them). Each run that changes the plan
is kept in goal_budget_reflections, which the settings screen lists and a notification announces.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound
from ..services import capsule_service, client_service, client_settings_service, goal_budget_record, notification_service, registry_service
from ..services.budget_plan_store import (
    create_plan_lines,
    find_budget_plan_id,
    resolve_budget_plan_id,
    retire_plan_lines,
    update_plan_lines,
)
from ..services.cache_service import invalidate_client
from ..services.goal_plan_service import (
    GOAL_DRAWDOWN_NAME, GOAL_LINE_NAME, GOAL_SOURCE, GOAL_TRANSFER_NAME, REFLECTION_NOTIFICATION, earmark_parts, earmarked_events,
    plan as goal_plan,
)
from ..services.life_scenario_scope import get_goal, lock_client
from ..services.periods import add_months
from ..services.product_reserve_plan import SOURCE as PRODUCT_SOURCE, plan as product_plan

logger = logging.getLogger(__name__)

MONTHS = 12
TRIGGERS = ("month", "change", "settings", "manual")
# A run keeps this many changed rows for the history; the count is always whole.
KEPT_ROWS = 100


def _client(db: Session, client_id: int) -> models.Client:
    client = client_service.get_active_by_id(db, client_id)
    if client is None:
        raise NotFound("クライアントが見つかりません。")
    return client


def current_range(db: Session, client_id: int) -> list[str]:
    start = registry_service.client_today(db, client_id).strftime("%Y-%m")
    return [add_months(start, offset) for offset in range(MONTHS)]


def settings(db: Session, client_id: int) -> dict:
    return client_settings_service.reflection_settings(_client(db, client_id))


def _with(current: dict, patch: dict | None) -> dict:
    """The settings with a change laid over them, unsaved (for a preview of the change)."""
    if not patch:
        return current
    merged = {**current, "goal": dict(current["goal"]), "products": dict(current["products"])}
    for group in ("goal", "products"):
        merged[group].update({key: value for key, value in (patch.get(group) or {}).items() if value is not None})
    if patch.get("enabled") is not None:
        merged["enabled"] = bool(patch["enabled"])
    return merged


def _compute(db: Session, client_id: int, current: dict) -> dict:
    periods = current_range(db, client_id)
    plan_id = find_budget_plan_id(db, client_id)
    goal = get_goal(db, client_id)
    goal_part = goal_plan(db, client_id, periods[0], periods[-1], plan_id,
                          {**current["goal"], "since": current["since"]}) if goal is not None else None
    products = product_plan(db, client_id, periods[0], periods[-1], plan_id, current["products"]["base"],
                            current["products"]["held"]) if current["products"]["enabled"] else None
    changes = [*_readable(goal_part, "goal"), *_readable(products, "products")]
    warnings = [*(goal_part or {}).get("warnings", []), *(products or {}).get("warnings", [])]
    currency = (goal_part or products or {}).get("currency")
    return {"periods": periods, "currency": currency, "goal": goal_part, "products": products,
            "scenario": goal_part["scenario"] if goal_part else None, "changes": changes, "warnings": warnings}


def _readable(planned: dict | None, origin: str) -> list[dict]:
    """The rows a run changes, as the screen and the history show them."""
    if not planned:
        return []
    rows = []
    for change in planned["changes"]:
        if not change["changed"]:
            continue
        kind = change.get("kind", "capsule")
        rows.append({
            "origin": origin, "period": change["period"], "kind": kind,
            "capsule_name": change.get("capsule_name"), "account_name": change.get("account_name"),
            "source_account_name": change.get("source_account_name"), "new_capsule": change.get("new_capsule", False),
            "current": change["current"], "new": change["new"], "retire": change["retire"],
        })
    return rows


def preview(db: Session, client_id: int, patch: dict | None = None) -> dict:
    """What a run would change now, with the saved settings or these changed ones; nothing is saved."""
    current = _with(settings(db, client_id), patch)
    computed = _compute(db, client_id, current)
    return {"settings": current, "periods": computed["periods"], "currency": computed["currency"],
            "scenario": computed["scenario"], "changes": computed["changes"], "warnings": computed["warnings"]}


def run(db: Session, client_id: int, trigger: str) -> dict:
    """Write this month and the 11 after it as the settings say, and keep the run when it changed something."""
    assert trigger in TRIGGERS, trigger
    lock_client(db, client_id)
    try:
        current = settings(db, client_id)
        computed = _compute(db, client_id, current)
        plan_id = find_budget_plan_id(db, client_id)
        if plan_id is None and computed["changes"]:
            plan_id = resolve_budget_plan_id(db, client_id, commit=False)
        written = 0
        if computed["goal"] is not None:
            written += _write_goal(db, client_id, computed["goal"], plan_id)
        if computed["products"] is not None:
            written += _write_products(db, client_id, computed["products"], plan_id)
        periods = computed["periods"]
        client_settings_service.merge_reflection_settings(db, _client(db, client_id), {"last_period": periods[0]},
                                                          period=periods[0], commit=False)
        if written or trigger in ("month", "manual"):
            goal_budget_record.record(db, client_id, scenario_id=computed["scenario"]["id"] if computed["scenario"] else None,
                                      start_period=periods[0], end_period=periods[-1],
                                      summary={"trigger": trigger, "changes": written, "rows": computed["changes"][:KEPT_ROWS],
                                               "warnings": computed["warnings"], "currency": computed["currency"],
                                               "settings": {"goal": current["goal"], "products": current["products"]}})
        # The plan now covers this month: the reminder to make it is answered.
        notification_service.resolve_kind(db, client_id, REFLECTION_NOTIFICATION)
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return {"trigger": trigger, "changes": written, "periods": computed["periods"], "warnings": computed["warnings"]}


def run_due(db: Session, client_id: int) -> dict | None:
    """The start-of-month run: once a month while 自動反映 is on."""
    current = settings(db, client_id)
    if not current["enabled"] or current["last_period"] == current_range(db, client_id)[0]:
        return None
    return run(db, client_id, "month")


def run_due_logged(db: Session, client_id: int) -> None:
    """run_due for the daily loop and sign-in: a failure is logged and the next one tries again."""
    try:
        run_due(db, client_id)
    except Exception:
        db.rollback()
        logger.exception("Plan reflection failed for client_id=%s", client_id)


def run_due_all(db: Session) -> None:
    for client_id in client_settings_service.reflection_client_ids(db):
        run_due_logged(db, client_id)


def after_change(db: Session, client_id: int) -> None:
    """After a change of what the plan is made from: a run when 自動反映 is on. A failure is logged, never
    failing the change that was already saved; the next run (or 今すぐ反映) catches up."""
    try:
        if settings(db, client_id)["enabled"]:
            run(db, client_id, "change")
    except Exception:
        db.rollback()
        logger.exception("Plan reflection after a change failed for client_id=%s", client_id)


def save_settings(db: Session, client_id: int, patch: dict) -> dict:
    """Save the settings; with 自動反映 on, the plan follows them at once."""
    periods = current_range(db, client_id)
    saved = client_settings_service.merge_reflection_settings(db, _client(db, client_id), patch, period=periods[0])
    result = run(db, client_id, "settings") if saved["enabled"] else None
    return {"settings": settings(db, client_id), "run": result}


def _write_goal(db: Session, client_id: int, planned: dict, plan_id: int | None) -> int:
    """The goal's rows: its earmarks made or kept in step with the events, then retire / update / create."""
    changed = [change for change in planned["changes"] if change["changed"]]
    events = {event.id: event for event in earmarked_events(db, client_id, get_goal(db, client_id))}
    targets = earmark_parts(db, list(events.values()))
    existing = capsule_service.goal_capsules(db, client_id, list(events))
    for event_id, capsule in existing.items():
        capsule_service.sync_goal_capsule(db, client_id, capsule.id, targets[event_id])
    first = planned["periods"][0]
    monthly: dict[int, int] = {}
    for change in planned["changes"]:
        if change["kind"] == "capsule" and change["period"] == first and not change["retire"] and change["event_id"] is not None:
            monthly[change["event_id"]] = monthly.get(change["event_id"], 0) + change["new_minor"]
    made: dict[int, int] = {}
    for change in planned["changes"]:
        if change["new_capsule"] and not change["retire"] and change["event_id"] not in made:
            event = events[change["event_id"]]
            made[event.id] = capsule_service.create_goal_capsule(
                db, client_id, event_id=event.id, name=event.name, parts=targets[event.id], monthly_minor=monthly.get(event.id, 0),
            ).id
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
        elif change["kind"] == "transfer":
            row.update(target_type="account", source_account_id=change["source_account_id"], name=GOAL_TRANSFER_NAME)
        else:
            row.update(target_type="account", name=GOAL_LINE_NAME)
        creates.append(row)
    _apply(db, client_id, retires, updates, creates)
    # Writing rows re-sums an earmark's monthly amount month by month; a goal earmark's is its first month's.
    for event_id, minor in monthly.items():
        capsule_id = existing[event_id].id if event_id in existing else made.get(event_id)
        if capsule_id is not None:
            capsule_service.set_goal_capsule_monthly(db, client_id, capsule_id, minor)
    return len(changed)


def _write_products(db: Session, client_id: int, planned: dict, plan_id: int | None) -> int:
    changed = [change for change in planned["changes"] if change["changed"]]
    retires = [change["line_id"] for change in changed if change["retire"]]
    updates = [{"id": change["line_id"], "amount": change["new"], "manual_override": False}
               for change in changed if not change["retire"] and change["line_id"] is not None]
    creates = [{"plan_id": plan_id, "target_period": change["period"], "line_type": "allocation", "target_type": "capsule",
                "target_id": change["capsule_id"], "account_id": change["account_id"], "amount": change["new"],
                "source": PRODUCT_SOURCE, "source_kind": PRODUCT_SOURCE, "cash_treatment": "auto"}
               for change in changed if not change["retire"] and change["line_id"] is None]
    _apply(db, client_id, retires, updates, creates)
    return len(changed)


def _apply(db: Session, client_id: int, retires: list, updates: list, creates: list) -> None:
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
