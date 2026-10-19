"""The plan page's account editor: an account's month as records, and the user's own records (WP19).

Each account kind has its sections -- an asset account 予算 (allocations into it) and
取り崩し, an expense or income subject 予算, a liability 返済 and 借入. A section lists
every record behind its budget with where it comes from: the goal, an automatic
transaction, a card statement estimate, or the user. Only the user's records are
written here, one per section; the others change where they come from.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import schemas
from ..domain.errors import Conflict, NotFound, Refused
from ..services import automatic_recording_service, ledger_service
from ..services.budget_plan_service import month_plan_lines
from ..services.budget_plan_store import create_plan_lines, delete_plan_line, get_plan_line, resolve_budget_plan_id, update_plan_lines
from ..services.cache_service import invalidate_client
from ..services.goal_plan_service import GOAL_SOURCE
from ..services.money_storage import money_client_currency

SECTIONS: dict[str, list[tuple[str, str]]] = {
    "asset": [("allocation", "予算"), ("drawdown", "取り崩し")],
    "expense": [("expense", "予算")],
    "income": [("income", "予算")],
    "liability": [("debt_payment", "返済"), ("borrowing", "借入")],
}
TYPE_LABELS = {"income": "収入", "expense": "支出", "allocation": "配分", "debt_payment": "返済", "borrowing": "借入", "drawdown": "取り崩し"}
ORIGINS = {"goal": "ゴールによる設定", "registry": "自動取引による設定", "card": "カード請求の見込み", "manual": "ユーザーによる追加"}


def _origin(line: dict) -> str:
    # A row saved from an automatic transaction is its correction for the month; the user's rows add to it.
    source = line.get("source")
    if GOAL_SOURCE in (source, line.get("source_kind")):
        return "goal"
    if source == "registry":
        return "registry"
    if source == "credit_settlement" or (source != "manual" and line.get("source_kind") == "credit_settlement"):
        return "card"
    return "manual"


def _account(db: Session, client_id: int, account_id: int):
    account = ledger_service.get_account(db, client_id, account_id)
    if account is None:
        raise NotFound("口座・科目が見つかりません。")
    return account


def _section_actual(lines: list[dict]) -> float:
    # A row without a source account claims the account's whole side of the month.
    whole = next((line for line in lines if not line.get("source_account_id")), None)
    return float(whole.get("actual") or 0) if whole else sum(float(line.get("actual") or 0) for line in lines)


def _record_name(line: dict, origin: str, fallback: str) -> str:
    # An automatic transaction's record is named after the automatic transactions it adds up.
    items = [item.get("name") for item in line.get("registry_items") or [] if item.get("name")]
    if origin == "registry" and items:
        return "・".join(dict.fromkeys(items))
    return line.get("name") or line.get("target_name") or fallback


def account_view(db: Session, client_id: int, period: str, account_id: int) -> dict:
    account = _account(db, client_id, account_id)
    month = [line for line in month_plan_lines(db, client_id, period) if line.get("account_id") == account.id]
    lines = [line for line in month if line.get("target_type") != "capsule"]
    # Earmarks set part of this account aside; they are budgeted on their own rows, listed here for reference.
    earmarks = [{"capsule_id": line.get("target_id"), "name": line.get("target_name") or line.get("name"),
                 "amount": float(line.get("budget_amount") or 0), "goal": bool(line.get("goal_earmark"))}
                for line in month if line.get("target_type") == "capsule"]
    known = SECTIONS.get(account.account_type, [])
    keys = [key for key, _ in known] + sorted({line["line_type"] for line in lines} - {key for key, _ in known})
    sections = []
    for key in keys:
        rows = [line for line in lines if line.get("line_type") == key]
        records = []
        for line in rows:
            origin = _origin(line)
            records.append({
                "id": line.get("id"), "name": _record_name(line, origin, account.name),
                "amount": float(line.get("budget_amount") or 0), "origin": origin, "origin_label": ORIGINS[origin],
                # A user's 返済 record stands in for the card statement estimate, which stays beside it.
                "card_estimate": float(line.get("suggested_amount") or 0)
                if origin == "manual" and line.get("suggested_source") == "credit_settlement" else None,
                "editable": origin == "manual" and line.get("id") is not None,
                "source_account_id": line.get("source_account_id"),
            })
        sections.append({
            "key": key, "label": dict(known).get(key, TYPE_LABELS.get(key, key)), "mismatch": key not in dict(known),
            "total": round(sum(record["amount"] for record in records), 2), "actual": round(_section_actual(rows), 2) if rows else 0.0,
            "records": records,
            "can_add": key in dict(known) and not any(r["origin"] == "manual" and not r["source_account_id"] for r in records),
        })
    scheduled = [item for item in automatic_recording_service.scheduled_in_period(db, client_id, period)["items"]
                 if account.id in (item.get("account_id"), item.get("counter_account_id"))]
    return {"account": {"id": account.id, "name": account.name, "kind": account.account_type}, "period": period,
            "currency": money_client_currency(db, client_id), "sections": sections, "earmarks": earmarks, "scheduled": scheduled}


def add_record(db: Session, client_id: int, payload: schemas.PlanRecordCreate) -> dict:
    account = _account(db, client_id, payload.account_id)
    if payload.section not in dict(SECTIONS.get(account.account_type, [])):
        raise Refused("この口座・科目には追加できない種類です。", status_code=422)
    try:
        create_plan_lines(db, client_id, [{
            "plan_id": resolve_budget_plan_id(db, client_id, commit=False), "target_period": payload.period,
            "line_type": payload.section, "target_type": "account", "account_id": account.id,
            "name": (payload.name or "").strip() or account.name, "amount": payload.amount,
            "source": "manual", "source_kind": "manual", "manual_override": True, "cash_treatment": "auto",
        }], commit=False)
        db.commit()
    except ValueError as error:
        db.rollback()
        raise Conflict("この種類にはすでにユーザーのレコードがあります。そのレコードを編集してください。") from error
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return account_view(db, client_id, payload.period, account.id)


def _own_record(db: Session, client_id: int, record_id: int):
    line = get_plan_line(db, client_id, record_id)
    # Earmark rows and rows without an account are not an account's records.
    if line is None or not line.is_active or line.account_id is None or line.target_type == "capsule":
        raise NotFound("レコードが見つかりません。")
    if _origin({"source": line.source, "source_kind": line.source_kind}) != "manual":
        raise Refused("ゴール・自動取引・カード請求のレコードは、それぞれの設定元で変更してください。", status_code=422)
    return line


def amend_record(db: Session, client_id: int, record_id: int, payload: schemas.PlanRecordUpdate) -> dict:
    line = _own_record(db, client_id, record_id)
    period, account_id = line.target_period, line.account_id
    patch = {"id": line.id, "amount": payload.amount, "manual_override": True}
    if payload.name is not None and payload.name.strip():
        patch["name"] = payload.name.strip()
    try:
        update_plan_lines(db, client_id, [patch], commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return account_view(db, client_id, period, account_id)


def delete_record(db: Session, client_id: int, record_id: int) -> dict:
    line = _own_record(db, client_id, record_id)
    period, account_id = line.target_period, line.account_id
    try:
        delete_plan_line(db, client_id, line.id, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return account_view(db, client_id, period, account_id)
