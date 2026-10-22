"""Bring every notification kind up to date for a client.

Each generator returns the notifications that should exist now; adding a kind is
one more entry in GENERATORS. The screens call sync when they open (an explicit
POST), so nothing writes for a client nobody is using.

A generator's dedupe_key is a stable hash of its reasons (which requests, which
actions, which issue codes), so 見送り holds while the same reasons persist and a
new reason brings a new notification.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.orm import Session

from ..services import (
    ai_change_request_store, data_health_service, ledger_service,
    notification_service, period_close_service,
)
from ..services.client_settings_service import client_language, pick
from ..services.periods import add_months, period_to_range
from ..services import goal_budget_record, goal_plan_service

APPROVAL_PENDING = "approval_pending"
UNMATCHED = "unmatched"
DATA_HEALTH = "data_health"
MONTH_CLOSE = "month_close"
# Longer lists end in a count; the screen the notification opens has the rest.
BODY_LINES = 10


def _notification(kind: str, reasons: list, title: str, lines: list[str], link: str, payload: dict, language: str = "ja") -> list[dict]:
    # The key is the reasons alone, so a language change rewrites the text without reopening a dismissal.
    key = hashlib.sha256(json.dumps(sorted(reasons)).encode()).hexdigest()[:16]
    shown = lines[:BODY_LINES]
    if len(lines) > len(shown):
        shown.append(pick(language, f"ほか{len(lines) - len(shown)}件", f"and {len(lines) - len(shown)} more"))
    return [{"dedupe_key": f"{kind}:{key}", "title": title, "body": "\n".join(shown),
             "payload": {**payload, "count": len(lines)}, "link": link}]


def approval_notifications(db: Session, client_id: int, period: str) -> list[dict]:
    rows = ai_change_request_store.list_for_client(db, client_id, status="pending")
    if not rows:
        return []
    language = client_language(db, client_id)
    return _notification(APPROVAL_PENDING, [row.id for row in rows],
                         pick(language, f"承認待ちの AI 変更が{len(rows)}件あります", f"{len(rows)} change(s) from AI awaiting approval"),
                         [f"#{row.id} {row.resource}{pick(language, '・', ' · ')}{row.action}" for row in rows],
                         "/automation/approvals", {"ids": [row.id for row in rows]}, language)


def unmatched_notifications(db: Session, client_id: int, period: str) -> list[dict]:
    rows = ledger_service.list_proposals(db, client_id, status="pending")
    if not rows:
        return []
    language = client_language(db, client_id)
    return _notification(UNMATCHED, [row.id for row in rows],
                         pick(language, f"未反映の候補が{len(rows)}件あります", f"{len(rows)} automatic transaction(s) not yet recorded"),
                         [f"{row.date.isoformat()} {row.description}" for row in rows],
                         "/ledger/auto", {"ids": [row.id for row in rows]}, language)


def data_health_notifications(db: Session, client_id: int, period: str) -> list[dict]:
    issues = [issue for issue in data_health_service.check_data_health(db, client_id)["issues"]
              if issue["count"] > 0 and issue["severity"] in ("warning", "error")]
    if not issues:
        return []
    language = client_language(db, client_id)
    return _notification(DATA_HEALTH, [issue["code"] for issue in issues],
                         pick(language, "データ健全性に異常があります", "Data health issues found"),
                         [pick(language, f"{issue['title']}（{issue['count']}件）", f"{issue['title']} ({issue['count']})") for issue in issues],
                         "/debug/data-health", {"codes": [issue["code"] for issue in issues]}, language)


def month_close_notifications(db: Session, client_id: int, period: str) -> list[dict]:
    """The month before `period` is over but not closed; a month with no entries has nothing to confirm."""
    previous = add_months(period, -1)
    start, end = period_to_range(previous)
    if period_close_service.is_closed(db, client_id, previous):
        return []
    rows, _ = ledger_service.list_transactions(db, client_id, start_date=start, end_date=end - timedelta(days=1), limit=1)
    if not rows:
        return []
    # The ledger month view holds the close; the link opens that month.
    language = client_language(db, client_id)
    return _notification(MONTH_CLOSE, [previous], pick(language, f"{previous} が締められていません", f"{previous} is not closed"),
                         [pick(language, "記録を確認して月を締めてください。", "Check the records and close the month.")],
                         f"/ledger?month={previous}", {"period": previous}, language)


GENERATORS: dict[str, Callable[[Session, int, str], list[dict]]] = {
    goal_plan_service.REFLECTION_NOTIFICATION: goal_plan_service.reflection_notifications,
    goal_budget_record.REFLECTED_NOTIFICATION: goal_budget_record.reflected_notifications,
    APPROVAL_PENDING: approval_notifications,
    UNMATCHED: unmatched_notifications,
    DATA_HEALTH: data_health_notifications,
    MONTH_CLOSE: month_close_notifications,
}


def sync(db: Session, client_id: int, period: str) -> dict:
    try:
        notification_service.purge(db, client_id)
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
