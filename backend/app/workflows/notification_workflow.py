"""Bring every notification kind up to date for a client.

Each generator returns the notifications that should exist now; adding a kind is
one more entry in GENERATORS. The screens call sync when they open (an explicit
POST), so nothing writes for a client nobody is using.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from ..services import notification_service
from . import goal_budget_workflow

GENERATORS: dict[str, Callable[[Session, int, str], list[dict]]] = {
    goal_budget_workflow.REFLECTION_NOTIFICATION: goal_budget_workflow.reflection_notifications,
}


def sync(db: Session, client_id: int, period: str) -> dict:
    try:
        for kind, generate in GENERATORS.items():
            notification_service.sync(db, client_id, kind, generate(db, client_id, period))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return listing(db, client_id)


def listing(db: Session, client_id: int) -> dict:
    return {
        "items": [notification_service.describe(row) for row in notification_service.visible(db, client_id)],
        "hidden_count": notification_service.hidden_count(db, client_id),
    }
