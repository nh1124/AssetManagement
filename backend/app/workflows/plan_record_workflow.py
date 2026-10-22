"""The plan page's account editor: an account's month as records, and the user's own records (WP19).

Each account kind has its sections -- an asset account 予算 (allocations into it) and
取り崩し, an expense or income subject 予算, a liability 返済 and 借入. A section lists
every record behind its budget with where it comes from: the goal, an automatic
transaction, a card statement estimate, or the user. Only the user's records are
written here -- several per section, one per name (WP27) -- and a record marked 自動扱い
becomes an automatic transaction (posting on its day or only budgeting); the others change
where they come from.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .. import schemas
from ..domain.errors import Conflict, NotFound, Refused
from ..services import automatic_recording_service, ledger_service, registry_service
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
        raise NotFound("口座・科目が見つかりません。", en="Account not found.")
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
            "can_add": key in dict(known),
        })
    scheduled = [item for item in automatic_recording_service.scheduled_in_period(db, client_id, period)["items"]
                 if account.id in (item.get("account_id"), item.get("counter_account_id"))]
    return {"account": {"id": account.id, "name": account.name, "kind": account.account_type}, "period": period,
            "currency": money_client_currency(db, client_id), "sections": sections, "earmarks": earmarks, "scheduled": scheduled}


# 自動扱い: the automatic transaction a record becomes, by section -- (kind, the account is the destination).
AUTOMATIC_KINDS = {"expense": ("expense", True), "income": ("income", False), "allocation": ("transfer", True), "debt_payment": ("debt", True)}


def _automatic_entry(db: Session, client_id: int, account, payload: schemas.PlanRecordCreate) -> None:
    automatic = payload.automatic
    if payload.section not in AUTOMATIC_KINDS:
        raise Refused("この区分は自動扱いにできません。", en="This kind cannot be made automatic.", status_code=422)
    if automatic.counter_account_id is None:
        raise Refused(
            "自動扱いには相手の口座（支払元・入金先・振替元）を選んでください。",
            en="To make it automatic, choose the other account (paid from, deposit to or transfer from).", status_code=422,
        )
    if automatic.end_period is not None and automatic.end_period < automatic.start_period:
        raise Refused("終了月は開始月以降にしてください。", en="The end month must be on or after the start month.", status_code=422)
    kind, inbound = AUTOMATIC_KINDS[payload.section]
    counter = automatic.counter_account_id
    year, month = (int(part) for part in automatic.start_period.split("-"))
    end = None
    if automatic.end_period:
        end_year, end_month = (int(part) for part in automatic.end_period.split("-"))
        end = date(end_year + end_month // 12, end_month % 12 + 1, 1) - timedelta(days=1)
    registry_service.create_entry(db, client_id, {
        "name": (payload.name or "").strip() or account.name, "kind": kind, "amount": payload.amount,
        "source_account_id": counter if inbound else account.id, "destination_account_id": account.id if inbound else counter,
        "budget_account_id": account.id, "repeat_mode": "indefinite", "frequency": automatic.frequency,
        "day_of_month": automatic.day_of_month, "month_of_year": month if automatic.frequency == "Yearly" else None,
        "start_date": date(year, month, 1), "end_date": end, "budget_active": True, "is_active": True,
        "records_transactions": automatic.records_transactions,
    })


def add_record(db: Session, client_id: int, payload: schemas.PlanRecordCreate) -> dict:
    account = _account(db, client_id, payload.account_id)
    if payload.section not in dict(SECTIONS.get(account.account_type, [])):
        raise Refused("この口座・科目には追加できない種類です。", en="This kind cannot be added to this account.", status_code=422)
    if payload.automatic is not None:
        try:
            _automatic_entry(db, client_id, account, payload)
            db.commit()
        except Exception:
            db.rollback()
            raise
        invalidate_client(client_id)
        return account_view(db, client_id, payload.period, account.id)
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
        raise Conflict(
            "同じ名前のレコードがあります。名前（理由）を変えるか、そのレコードを編集してください。",
            en="A record with this name already exists. Change the name (reason) or edit that record.",
        ) from error
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return account_view(db, client_id, payload.period, account.id)


def _own_record(db: Session, client_id: int, record_id: int):
    line = get_plan_line(db, client_id, record_id)
    # Earmark rows and rows without an account are not an account's records.
    if line is None or not line.is_active or line.account_id is None or line.target_type == "capsule":
        raise NotFound("レコードが見つかりません。", en="Record not found.")
    if _origin({"source": line.source, "source_kind": line.source_kind}) != "manual":
        raise Refused(
            "ゴール・自動取引・カード請求のレコードは、それぞれの設定元で変更してください。",
            en="Change goal, automatic transaction and card bill records where they are set up.", status_code=422,
        )
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
