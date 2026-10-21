"""The record of 計画への反映 runs: which months the plan was made for, what changed, and why (WP27)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import models


def covering(db: Session, client_id: int, period: str) -> models.GoalBudgetReflection | None:
    """The latest applied reflection whose months include this one."""
    return db.query(models.GoalBudgetReflection).filter(
        models.GoalBudgetReflection.client_id == client_id,
        models.GoalBudgetReflection.start_period <= period,
        models.GoalBudgetReflection.end_period >= period,
    ).order_by(models.GoalBudgetReflection.applied_at.desc(), models.GoalBudgetReflection.id.desc()).first()


def record(
    db: Session, client_id: int, *, scenario_id: int, start_period: str, end_period: str, summary: dict,
) -> models.GoalBudgetReflection:
    """Add one record in the caller's transaction."""
    row = models.GoalBudgetReflection(
        client_id=client_id, scenario_id=scenario_id, start_period=start_period, end_period=end_period, summary=summary,
    )
    db.add(row)
    db.flush()
    return row


REFLECTED_NOTIFICATION = "plan_reflected"
HISTORY = 10
# An automatic run is announced for this long, unless 見送り hides it sooner.
ANNOUNCED_DAYS = 14
TRIGGER_LABELS = {"month": "月の初め", "change": "変更", "settings": "設定の保存", "manual": "今すぐ反映"}


def describe(row: models.GoalBudgetReflection) -> dict:
    summary = row.summary or {}
    # A record from the old preview dialog has no trigger: it was made by hand.
    return {"id": row.id, "applied_at": row.applied_at.isoformat() if row.applied_at else None,
            "trigger": summary.get("trigger", "manual"), "start_period": row.start_period, "end_period": row.end_period,
            "changes": int(summary.get("changes") or 0), "rows": summary.get("rows", []), "warnings": summary.get("warnings", []),
            "currency": summary.get("currency")}


def history(db: Session, client_id: int) -> list[dict]:
    """The latest runs, newest first."""
    rows = db.query(models.GoalBudgetReflection).filter_by(client_id=client_id).order_by(
        models.GoalBudgetReflection.applied_at.desc(), models.GoalBudgetReflection.id.desc()).limit(HISTORY).all()
    return [describe(row) for row in rows]


def reflected_notifications(db: Session, client_id: int, period: str) -> list[dict]:
    """「計画を自動で更新しました」 for the latest automatic run that changed the plan, for two weeks."""
    since = datetime.utcnow() - timedelta(days=ANNOUNCED_DAYS)
    row = db.query(models.GoalBudgetReflection).filter(
        models.GoalBudgetReflection.client_id == client_id, models.GoalBudgetReflection.applied_at >= since,
    ).order_by(models.GoalBudgetReflection.applied_at.desc(), models.GoalBudgetReflection.id.desc()).first()
    if row is None:
        return []
    shown = describe(row)
    if shown["trigger"] not in ("month", "change", "settings") or not shown["changes"]:
        return []
    lines = [f"{shown['start_period']}〜{shown['end_period']}：{shown['changes']}件の行を変更しました（{TRIGGER_LABELS[shown['trigger']]}）。"]
    lines += shown["warnings"][:3]
    return [{"dedupe_key": f"{REFLECTED_NOTIFICATION}:{row.id}", "title": "計画を自動で更新しました", "body": "\n".join(lines),
             "payload": {"record_id": row.id}, "link": "/plan?reflection=history"}]

