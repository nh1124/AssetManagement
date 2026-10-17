"""Notifications: one table for everything that needs the user's attention.

Each kind has a generator elsewhere that says which notifications should exist
right now (sync). This module owns the rows and the user's decisions on them:

- open: shown;
- snoozed: 後で確認, hidden until snoozed_until, then shown again;
- dismissed: 見送り, hidden while the same reasons hold (a change of reasons is a
  new dedupe_key, so a new notification; reasons that go away and come back are
  shown again);
- done: resolved by the action itself or because the reasons went away; a done
  notification whose reasons come back is reopened.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models

ACTIVE = ("open", "snoozed")
# Everything that is not done yet; a dismissal is a decision about the current reasons only.
UNRESOLVED = (*ACTIVE, "dismissed")


def _now(now: datetime | None) -> datetime:
    return now or datetime.utcnow()


def sync(db: Session, client_id: int, kind: str, desired: list[dict], *, now: datetime | None = None) -> None:
    """Make this kind's notifications match what its generator says should exist; flushes only."""
    now = _now(now)
    rows = {row.dedupe_key: row for row in db.query(models.Notification).filter_by(client_id=client_id, kind=kind)}
    wanted = set()
    for item in desired:
        key = item["dedupe_key"]
        wanted.add(key)
        fields = {name: item.get(name) for name in ("title", "body", "payload", "link")}
        row = rows.get(key)
        if row is None:
            db.add(models.Notification(client_id=client_id, kind=kind, dedupe_key=key, status="open",
                                       created_at=now, updated_at=now, **fields))
            continue
        for name, value in fields.items():
            setattr(row, name, value)
        if row.status == "done":
            row.status, row.resolved_at, row.snoozed_until = "open", None, None
    for key, row in rows.items():
        if key not in wanted and row.status in UNRESOLVED:
            row.status, row.resolved_at = "done", now
    db.flush()


def resolve_kind(db: Session, client_id: int, kind: str, *, now: datetime | None = None) -> None:
    """The action a kind asks for was taken: close its notifications that are not done; flushes only."""
    db.query(models.Notification).filter(
        models.Notification.client_id == client_id, models.Notification.kind == kind,
        models.Notification.status.in_(UNRESOLVED),
    ).update({"status": "done", "resolved_at": _now(now)}, synchronize_session="fetch")
    db.flush()


def visible(db: Session, client_id: int, *, now: datetime | None = None) -> list[models.Notification]:
    """Open notifications and snoozed ones whose time has come, newest first."""
    now = _now(now)
    return db.query(models.Notification).filter(
        models.Notification.client_id == client_id,
        or_(models.Notification.status == "open",
            (models.Notification.status == "snoozed") & (models.Notification.snoozed_until <= now)),
    ).order_by(models.Notification.updated_at.desc(), models.Notification.id.desc()).all()


def hidden_count(db: Session, client_id: int, *, now: datetime | None = None) -> int:
    """Snoozed notifications still waiting for their time."""
    return db.query(models.Notification).filter(
        models.Notification.client_id == client_id, models.Notification.status == "snoozed",
        models.Notification.snoozed_until > _now(now),
    ).count()


def get(db: Session, client_id: int, notification_id: int) -> models.Notification | None:
    return db.query(models.Notification).filter_by(id=notification_id, client_id=client_id).first()


def decide(db: Session, notification: models.Notification, action: str, *, until: datetime | None = None,
           now: datetime | None = None) -> models.Notification:
    """Record the user's decision: snooze until a time, dismiss, or reopen; commits."""
    now = _now(now)
    if until is not None and until.tzinfo is not None:
        # Rows hold naive UTC, like every other timestamp in this database.
        until = until.astimezone(timezone.utc).replace(tzinfo=None)
    if action == "snooze":
        if until is None or until <= now:
            raise ValueError("snooze needs a time in the future")
        notification.status, notification.snoozed_until = "snoozed", until
    elif action == "dismiss":
        notification.status, notification.snoozed_until = "dismissed", None
    elif action == "reopen":
        notification.status, notification.snoozed_until, notification.resolved_at = "open", None, None
    else:
        raise ValueError(f"unknown notification action {action!r}")
    notification.updated_at = now
    db.commit()
    db.refresh(notification)
    return notification


def describe(row: models.Notification) -> dict:
    return {
        "id": row.id, "kind": row.kind, "title": row.title, "body": row.body, "payload": row.payload or {},
        "link": row.link, "status": row.status,
        "snoozed_until": row.snoozed_until.isoformat() if row.snoozed_until else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
