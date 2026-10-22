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


def _notification(kind: str, reasons: list[str | int], title: str, lines: list[str], link: str, payload: dict, language: str = "ja", *, lead: str | None = None) -> list[dict]:
    # The key is the reasons alone, so a language change rewrites the text without reopening a dismissal.
    key = hashlib.sha256(json.dumps(sorted(reasons)).encode()).hexdigest()[:16]
    shown = lines[:BODY_LINES]
    if len(lines) > len(shown):
        shown.append(pick(language, f"ほか{len(lines) - len(shown)}件", f"and {len(lines) - len(shown)} more"))
    if lead is not None:
        shown.insert(0, lead)
    return [{"dedupe_key": f"{kind}:{key}", "title": title, "body": "\n".join(shown),
             "payload": {"count": len(lines), **payload}, "link": link}]


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


# Each issue opens the screen where the user can resolve it.
DATA_HEALTH_TEXT = {
    "account_earmarked_beyond_its_balance": (
        ("口座の残高より多く取り置いています（{n}口座）", "Accounts with more set aside than they hold ({n})"),
        ("取り置いた分まで使っています。資産 › 口座で確保額を減らすか、口座にお金を戻してください。", "Money set aside has been spent. Reduce what is set aside under Assets › Accounts, or move money back into the account."),
        "/assets/accounts",
    ),
    "entries_in_a_closed_period": (
        ("締めた月に後から記録した取引があります（{n}件）", "Entries added to a closed month ({n})"),
        ("内容を確認したら、その月の締めをやり直してください（締めを外して、もう一度締める）。", "Check them, then redo the month's close (reopen it and close it again)."),
        "/ledger",
    ),
    "capsule_without_account": (
        ("確保する口座が決まっていない取り置きがあります（{n}件）", "Earmarks without a funding account ({n})"),
        ("取り置きを開いて、確保する口座を設定してください。口座が決まるまで規則は何も確保しません。", "Open the earmark and choose the account it is set aside in. Its rules reserve nothing until then."),
        "/db/earmarks",
    ),
    "capsule_claim_negative_on_account": (
        ("確保額がマイナスになっている取り置きがあります（{n}件）", "Earmarks with a negative amount set aside ({n})"),
        ("使った記録が確保した額より多くなっています。資産 › 口座で確保額を調整してください。", "More was recorded as used than was set aside. Adjust it under Assets › Accounts."),
        "/assets/accounts",
    ),
    "capsule_beyond_its_declared_share": (
        ("口座の割り当てを超えて確保している取り置きがあります（{n}件）", "Earmarks holding more than their share of an account ({n})"),
        ("口座の残高が減ったか、確保額が多すぎます。確保額か資金元の割合を見直してください。", "The account's balance fell or too much is set aside. Review the amount or the funding share."),
        "/db/earmarks",
    ),
    "capsule_plan_does_not_total_its_target": (
        ("資金元の額の合計が目標額と合わない取り置きがあります（{n}件）", "Earmarks whose funding amounts do not add up to the target ({n})"),
        ("目標額を変えたときは、資金元の額も合わせてください。", "When the target changes, change the funding amounts to match."),
        "/db/earmarks",
    ),
    "capsule_funding_account_is_inactive": (
        ("無効にした口座を資金元にしている取り置きがあります（{n}件）", "Earmarks funded from an inactive account ({n})"),
        ("口座を有効に戻すか、取り置きの資金元を別の口座に変えてください。", "Reactivate the account or move the earmark to another account."),
        "/db/earmarks",
    ),
}


DATA_HEALTH_ITEMS = {
    "entries_in_a_closed_period": ("transaction_id", "{date} {description}", "{date} {description}"),
    "account_earmarked_beyond_its_balance": ("account_id", "{account_name}", "{account_name}"),
    "capsule_without_account": ("capsule_id", "{name}", "{name}"),
    "capsule_claim_negative_on_account": ("capsule_id", "{name}（{account_name}）", "{name} ({account_name})"),
    "capsule_beyond_its_declared_share": ("capsule_id", "{name}（{account_name}）", "{name} ({account_name})"),
    "capsule_plan_does_not_total_its_target": ("capsule_id", "{name}", "{name}"),
    "capsule_funding_account_is_inactive": ("capsule_id", "{name}（{account_name}）", "{name} ({account_name})"),
}


def data_health_notifications(db: Session, client_id: int, period: str) -> list[dict]:
    issues = data_health_service.check_data_health(db, client_id, audience="user")["issues"]
    language = client_language(db, client_id)
    notifications = []
    for issue in issues:
        if issue["count"] <= 0 or issue["severity"] not in ("warning", "error"):
            continue
        code = issue["code"]
        titles, leads, link = DATA_HEALTH_TEXT[code]
        items = issue["items"]
        closed = code == "entries_in_a_closed_period"
        id_field, ja_line, en_line = DATA_HEALTH_ITEMS[code]
        ids = [item[id_field] for item in items]
        lines = [
            item["name"] if id_field == "capsule_id" and not item.get("account_name")
            else pick(language, ja_line, en_line).format(**item)
            for item in items
        ]
        reasons = [f"{code}:{issue['fingerprint']}"]
        payload = {"code": code, "ids": ids, "count": issue["count"]}
        if closed:
            earliest = min(item["period"] for item in items)
            link += f"?month={earliest}"
            payload["period"] = earliest
        notifications += _notification(
            DATA_HEALTH, reasons, pick(language, *titles).format(n=issue["count"]),
            lines, link, payload, language, lead=pick(language, *leads),
        )
    return notifications


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
