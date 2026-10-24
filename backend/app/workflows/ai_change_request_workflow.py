from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any
from uuid import uuid4
from types import SimpleNamespace

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import Conflict, Invalid, NotFound, Refused
from ..domain.messages import Message, message_of
from ..domain.money import Money
from ..services import ai_change_request_store, mfa_service
from ..services.fx_service import get_client_currency
from ..services.ledger_service import (
    create_transaction,
    find_account_ids,
    propose_transaction,
    simple_legs,
)
from ..services.budget_plan_store import get_plan_line, update_plan_lines
from ..services.cache_service import invalidate_client
from ..services.capsule_service import apply_capsule_rules_for_transaction
from ..services.registry_service import get_entry, create_entry, update_entry, validate_account_refs, normalize_schedule, client_today, SCHEDULE_FIELDS
from ..services.schedule_rules import next_occurrence
from ..domain import ai_operations
from ..services.ai_policy_service import (
    AiOperationContext,
    ledger_write_is_direct,
    operation_mode,
    write_ai_audit_log,
)


# What a change request can carry, and the AI operation whose permission judges it (WP36).
SUPPORTED_OPERATIONS = {
    ("transactions", "create"): "transactions.create",
    ("monthly_plan_lines", "update"): "plan_lines.update",
    ("auto_transactions", "create"): "auto_transactions.create",
    ("auto_transactions", "update"): "auto_transactions.update",
}


def _refuse_if_denied(db: Session, client_id: int, key: str) -> None:
    """A change request cannot carry an operation the person denied the AI, at creation or at apply."""
    if operation_mode(db, client_id, key) == "deny":
        operation = ai_operations.BY_KEY[key]
        raise Refused(
            "This operation is not allowed for the AI in this client's settings.",
            ja="この操作は AI 操作の権限で禁止されています。",
            payload={"error": "ai_operation_denied", "operation": key,
                     "message": Message(f"{operation.en} is not allowed for the AI.", ja=f"「{operation.ja}」は AI 操作の権限で禁止されています。")},
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _model_dict(row: Any, fields: list[str]) -> dict[str, Any]:
    return {field: _jsonable(getattr(row, field)) for field in fields}


MONTHLY_PLAN_LINE_FIELDS = [
    "id",
    "target_period",
    "line_type",
    "target_type",
    "target_id",
    "account_id",
    "source_account_id",
    "name",
    "amount",
    "source",
    "source_kind",
    "identity_key",
    "manual_override",
    "cash_treatment",
    "is_active",
    "plan_id",
]

REGISTRY_ENTRY_FIELDS = ["id", "name", "kind", "amount", "currency", "source_account_id", "destination_account_id", "budget_account_id", "repeat_mode", "frequency", "frequency_days", "day_of_month", "month_of_year", "start_date", "end_date", "repeat_count", "next_due_date", "budget_active", "is_active", "note"]


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changes = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes.append({"field": key, "before": old, "after": new})
    return {"changes": changes, "count": len(changes)}


def _validate_transaction_create(db: Session, client_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    parsed = schemas.TransactionCreate(**payload)
    if parsed.currency is None:
        parsed.currency = get_client_currency(db, client_id)
    if parsed.amount <= 0:
        raise ValueError(Message("Transaction amount must be positive", ja="取引の金額は0より大きくしてください。"))

    account_ids = [value for value in [parsed.from_account_id, parsed.to_account_id] if value is not None]
    if account_ids:
        found_ids = find_account_ids(db, client_id, account_ids)
        missing = [account_id for account_id in account_ids if account_id not in found_ids]
        if missing:
            raise ValueError(Message(f"Account not found: {missing[0]}", ja=f"口座・科目が見つかりません（#{missing[0]}）。"))

    return parsed.model_dump(mode="json")


def _preview_transaction_create(db: Session, client_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate_transaction_create(db, client_id, payload)
    after = dict(data)
    after["id"] = None
    return {
        "target_ref": {"resource": "transactions"},
        "input_payload": data,
        "before_snapshot": {},
        "after_snapshot": after,
        "diff": _diff({}, after),
        "validation": {"valid": True, "messages": []},
        "precondition_hash": _stable_hash({}),
    }


def _preview_monthly_plan_lines_update(db: Session, client_id: int, target_ref: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    line_id = int(target_ref.get("id") or payload.get("id") or 0)
    if not line_id:
        raise ValueError(Message("Monthly plan line id is required", ja="計画の行を指定してください。"))
    line = get_plan_line(db, client_id, line_id)
    if not line:
        raise ValueError(Message("Monthly plan line not found", ja="計画の行が見つかりません。"))

    data = schemas.MonthlyPlanLineUpdate(**payload).model_dump(exclude_unset=True, mode="json")
    before = _model_dict(line, MONTHLY_PLAN_LINE_FIELDS)
    after = {**before, **data, "id": line_id}
    return {
        "target_ref": {"id": line_id},
        "input_payload": data,
        "before_snapshot": before,
        "after_snapshot": after,
        "diff": _diff(before, after),
        "validation": {"valid": True, "messages": []},
        "precondition_hash": _stable_hash(before),
    }


def _automatic_input(db: Session, client_id: int, payload: dict[str, Any], currency: str | None = None):
    parsed = schemas.RegistryEntryCreate(**payload)
    parsed.currency = parsed.currency or currency or get_client_currency(db, client_id)
    data = parsed.model_dump()
    validate_account_refs(db, client_id, data)
    schedule = SimpleNamespace(**data)
    normalize_schedule(schedule)
    return schedule, {key: _jsonable(getattr(schedule, key)) for key in data}


def _preview_automatic_create(db: Session, client_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    schedule, data = _automatic_input(db, client_id, payload)
    due = next_occurrence(schedule, client_today(db, client_id)) if schedule.is_active else None
    after = {**data, "id": None, "next_due_date": _jsonable(due)}
    return {
        "target_ref": {"resource": "auto_transactions"},
        "input_payload": data,
        "before_snapshot": {},
        "after_snapshot": after,
        "diff": _diff({}, after),
        "validation": {"valid": True, "messages": []},
        "precondition_hash": _stable_hash({}),
    }


def _preview_automatic_update(db: Session, client_id: int, target_ref: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    recurring_id = int(target_ref.get("id") or payload.get("id") or 0)
    if not recurring_id:
        raise ValueError(Message("Automatic transaction id is required", ja="自動取引を指定してください。"))
    recurring = get_entry(db, client_id, recurring_id)
    if not recurring:
        raise ValueError(Message("Automatic transaction not found", ja="自動取引が見つかりません。"))
    schedule, data = _automatic_input(db, client_id, payload, recurring.currency)
    before = _model_dict(recurring, REGISTRY_ENTRY_FIELDS)
    after = {**before, **data, "id": recurring_id}
    changed = any(before.get(key) != data.get(key) for key in SCHEDULE_FIELDS)
    if not schedule.is_active:
        after["next_due_date"] = None
    elif not recurring.is_active or changed:
        after["next_due_date"] = _jsonable(next_occurrence(schedule, client_today(db, client_id)))
    return {
        "target_ref": {"id": recurring_id},
        "input_payload": data,
        "before_snapshot": before,
        "after_snapshot": after,
        "diff": _diff(before, after),
        "validation": {"valid": True, "messages": []},
        "precondition_hash": _stable_hash(before),
    }


def preview_change_request(
    db: Session,
    client_id: int,
    payload: schemas.AiChangeRequestPreviewRequest | schemas.AiChangeRequestCreate,
) -> dict[str, Any]:
    resource = payload.resource.strip().lower()
    action = payload.action.strip().lower()
    if (resource, action) not in SUPPORTED_OPERATIONS:
        raise Invalid(f"Unsupported change request operation: {resource}:{action}")

    try:
        if (resource, action) == ("transactions", "create"):
            preview = _preview_transaction_create(db, client_id, payload.input_payload)
        elif (resource, action) == ("monthly_plan_lines", "update"):
            preview = _preview_monthly_plan_lines_update(db, client_id, payload.target_ref, payload.input_payload)
        elif (resource, action) == ("auto_transactions", "create"):
            preview = _preview_automatic_create(db, client_id, payload.input_payload)
        else:
            preview = _preview_automatic_update(db, client_id, payload.target_ref, payload.input_payload)
    except ValueError as exc:
        raise Invalid(message_of(exc)) from exc

    key = SUPPORTED_OPERATIONS[(resource, action)]
    _refuse_if_denied(db, client_id, key)
    return {
        "resource": resource,
        "action": action,
        "risk": ai_operations.BY_KEY[key].risk,
        **preview,
    }


def create_change_request(
    db: Session,
    client_id: int,
    actor_client_id: int,
    payload: schemas.AiChangeRequestCreate,
) -> models.AiChangeRequest:
    preview = preview_change_request(db, client_id, payload)
    idempotency_key = payload.idempotency_key or _stable_hash({
        "resource": preview["resource"],
        "action": preview["action"],
        "target_ref": preview["target_ref"],
        "input_payload": preview["input_payload"],
    })
    existing = ai_change_request_store.find_by_idempotency_key(db, client_id, idempotency_key)
    if existing:
        return existing

    fields = dict(
        created_by_client_id=actor_client_id,
        mcp_client_id=payload.mcp_client_id,
        source=payload.source,
        tool_name=payload.tool_name,
        resource=preview["resource"],
        action=preview["action"],
        risk=preview["risk"],
        status=payload.status,
        target_ref=preview["target_ref"],
        input_payload=preview["input_payload"],
        before_snapshot=preview["before_snapshot"],
        after_snapshot=preview["after_snapshot"],
        diff=preview["diff"],
        validation=preview["validation"],
        idempotency_key=idempotency_key,
        precondition_hash=preview["precondition_hash"],
        expires_at=payload.expires_at,
        result={},
    )
    row = ai_change_request_store.create(db, client_id, fields, commit=False)

    context = _operation_context(payload, preview)
    # A change request always waits for a person, whatever the operation's permission (WP36).
    log = write_ai_audit_log(
        db,
        client_id,
        context,
        "approval_required",
        result={"change_request_id": row.id, "status": row.status},
        commit=False,
    )
    log.approval_request_id = row.id
    db.commit()
    db.refresh(row)
    return row


def list_change_requests(
    db: Session,
    client_id: int,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[models.AiChangeRequest]:
    return ai_change_request_store.list_for_client(
        db, client_id, status=status_filter, limit=limit, offset=offset,
    )


def approve_change_request(
    db: Session,
    client_id: int,
    actor_client_id: int,
    change_request_id: int,
    step_up_token_payload: dict[str, Any] | None = None,
) -> models.AiChangeRequest:
    row = _get_change_request(db, client_id, change_request_id, for_update=True)
    if row.status not in {"draft", "pending"}:
        raise Invalid(
            f"Change request cannot be approved from status {row.status}",
            ja=f"この状態（{row.status}）の承認リクエストは承認できません。",
        )
    # Every approval is confirmed with the authenticator code (owner 2026-10-24, C10).
    if not mfa_service.mfa_enabled(db, actor_client_id):
        raise Refused("MFA setup required", ja="先にMFAを設定してください。")
    if not step_up_token_payload or step_up_token_payload.get("type") != "step_up" or str(step_up_token_payload.get("sub")) != str(actor_client_id):
        raise Refused("Step-up authentication required", ja="認証アプリのコードで本人確認をしてください。", status_code=401)
    row.status = "approved"
    row.approved_by_client_id = actor_client_id
    row.approved_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def reject_change_request(
    db: Session,
    client_id: int,
    change_request_id: int,
) -> models.AiChangeRequest:
    row = _get_change_request(db, client_id, change_request_id)
    if row.status in {"applied", "rejected"}:
        raise Invalid(
            f"Change request cannot be rejected from status {row.status}",
            ja=f"この状態（{row.status}）の承認リクエストは却下できません。",
        )
    row.status = "rejected"
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def refresh_preview(
    db: Session,
    client_id: int,
    change_request_id: int,
) -> models.AiChangeRequest:
    """Rebuild the preview against today's data (作り直し, §8-5).

    An approval or a failure belonged to the old preview, so an approved or failed
    request goes back to 承認待ち and is approved again; a failure's result stays as
    previous. A decided request (applied, rejected, expired) is not rebuilt.
    """
    row = _get_change_request(db, client_id, change_request_id, for_update=True)
    if row.status not in {"draft", "pending", "approved", "failed"}:
        raise Invalid(
            f"Change request cannot be rebuilt from status {row.status}",
            ja=f"この状態（{row.status}）の承認リクエストは作り直せません。",
        )
    preview_payload = schemas.AiChangeRequestPreviewRequest(
        source=row.source,
        tool_name=row.tool_name,
        resource=row.resource,
        action=row.action,
        mcp_client_id=row.mcp_client_id,
        target_ref=row.target_ref,
        input_payload=row.input_payload,
    )
    preview = preview_change_request(db, client_id, preview_payload)
    row.before_snapshot = preview["before_snapshot"]
    row.after_snapshot = preview["after_snapshot"]
    row.diff = preview["diff"]
    row.validation = preview["validation"]
    row.precondition_hash = preview["precondition_hash"]
    row.risk = preview["risk"]
    if row.status in {"approved", "failed"}:
        if row.status == "failed":
            row.result = {"previous": row.result or {}}
        row.status = "pending"
        row.approved_by_client_id = None
        row.approved_at = None
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def apply_change_request(
    db: Session,
    client_id: int,
    actor_client_id: int,
    change_request_id: int,
) -> models.AiChangeRequest:
    row = _get_change_request(db, client_id, change_request_id, for_update=True)
    if row.status == "applied":
        return row
    if row.status != "approved":
        raise Invalid(
            f"Change request must be approved before apply; current status is {row.status}",
            ja=f"承認リクエストは適用する前に承認が必要です（現在の状態：{row.status}）。",
        )
    # The permission may have changed since the request was made (WP36).
    _refuse_if_denied(db, client_id, SUPPORTED_OPERATIONS[(row.resource, row.action)])

    current_preview = preview_change_request(
        db,
        client_id,
        schemas.AiChangeRequestPreviewRequest(
            source=row.source,
            tool_name=row.tool_name,
            resource=row.resource,
            action=row.action,
            mcp_client_id=row.mcp_client_id,
            target_ref=row.target_ref,
            input_payload=row.input_payload,
        ),
    )
    if current_preview["precondition_hash"] != row.precondition_hash:
        row.status = "failed"
        row.result = {"error": "precondition_conflict", "message": "Target changed after preview; refresh preview before applying"}
        row.updated_at = datetime.utcnow()
        db.commit()
        raise Conflict(row.result["message"], payload=row.result)

    try:
        result = _apply_dispatch(db, client_id, row)
        row.status = "applied"
        row.applied_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        row.result = result

        context = AiOperationContext(
            source=row.source,
            tool_name=row.tool_name,
            resource=row.resource,
            action=row.action,
            risk=row.risk,
            mcp_client_id=row.mcp_client_id,
            request_summary=row.input_payload,
            diff_summary=row.diff,
            # The approval this apply rests on was confirmed with the authenticator code.
            mfa_verified=True,
        )
        log = write_ai_audit_log(
            db,
            client_id,
            context,
            "applied",
            result={"change_request_id": row.id, "status": row.status, **result},
            commit=False,
        )
        log.approval_request_id = row.id
        db.commit()
    except ValueError as exc:
        db.rollback()
        failed_row = _get_change_request(db, client_id, change_request_id, for_update=True)
        if failed_row.status == "approved":
            failed_row.status = "failed"
            failed_row.result = {"error": "apply_failed", "message": str(exc)}
            failed_row.updated_at = datetime.utcnow()
            db.commit()
        raise Invalid(message_of(exc)) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(row)
    invalidate_client(client_id)
    return row


def _apply_dispatch(db: Session, client_id: int, row: models.AiChangeRequest) -> dict[str, Any]:
    if (row.resource, row.action) == ("transactions", "create"):
        data = schemas.TransactionCreate(**row.input_payload).model_dump()
        if data["currency"] is None:
            data["currency"] = get_client_currency(db, client_id)
        data["amount_minor"] = Money.from_major(str(data.pop("amount")), data["currency"]).minor
        legs = data.pop("legs", None)
        from_account_id = data.pop("from_account_id", None)
        to_account_id = data.pop("to_account_id", None)
        if legs is None:
            legs = simple_legs(data["amount_minor"], from_account_id, to_account_id)
        # Posted directly only if the person allows the AI to record transactions;
        # otherwise it waits in 未反映 for a second decision (ai_write_path §1.3).
        if not ledger_write_is_direct(db, client_id):
            proposal = propose_transaction(
                db,
                client_id,
                origin="ai",
                origin_ref={"change_request_id": row.id},
                date=data["date"],
                description=data["description"],
                amount_minor=data["amount_minor"],
                currency=data["currency"],
                legs=legs,
            )
            # The AI's part is complete, so apply marks the request applied;
            # ledger posting still waits for the proposal's own approval.
            return {"proposal_id": proposal.id, "queued": True}
        tx = create_transaction(
            db,
            client_id=client_id,
            legs=legs,
            **data,
        )
        db.flush()
        apply_capsule_rules_for_transaction(db, tx, commit=False)
        return {"transaction_id": tx.id, "queued": False}

    if (row.resource, row.action) == ("monthly_plan_lines", "update"):
        line_id = int(row.target_ref.get("id") or row.input_payload.get("id") or 0)
        if not line_id:
            raise ValueError(Message("Monthly plan line id is required", ja="計画の行を指定してください。"))
        payload = {**row.input_payload, "id": line_id}
        saved = update_plan_lines(db, client_id, [payload], commit=False)
        return {"ids": [line.id for line in saved]}

    if (row.resource, row.action) == ("auto_transactions", "create"):
        data = schemas.RegistryEntryCreate(**row.input_payload).model_dump()
        recurring = create_entry(db, client_id, data)
        return {"registry_entry_id": recurring.id}

    if (row.resource, row.action) == ("auto_transactions", "update"):
        recurring_id = int(row.target_ref.get("id") or row.input_payload.get("id") or 0)
        if not recurring_id:
            raise ValueError(Message("Automatic transaction id is required", ja="自動取引を指定してください。"))
        recurring = get_entry(db, client_id, recurring_id)
        if not recurring:
            raise ValueError(Message("Automatic transaction not found", ja="自動取引が見つかりません。"))
        data = schemas.RegistryEntryCreate(**row.input_payload).model_dump(exclude_unset=True)
        recurring = update_entry(db, client_id, recurring_id, data)
        db.flush()
        return {"registry_entry_id": recurring.id}

    raise ValueError(f"Unsupported change request operation: {row.resource}:{row.action}")


def _get_change_request(
    db: Session,
    client_id: int,
    change_request_id: int,
    *,
    for_update: bool = False,
) -> models.AiChangeRequest:
    row = ai_change_request_store.get(db, client_id, change_request_id, for_update=for_update)
    if not row:
        raise NotFound("Change request not found", ja="承認リクエストが見つかりません。")
    return row


def _operation_context(
    payload: schemas.AiChangeRequestPreviewRequest | schemas.AiChangeRequestCreate,
    preview: dict[str, Any],
) -> AiOperationContext:
    return AiOperationContext(
        source=payload.source,
        tool_name=payload.tool_name,
        resource=preview["resource"],
        action=preview["action"],
        risk=preview["risk"],
        mcp_client_id=payload.mcp_client_id,
        request_summary=preview.get("input_payload", {}),
        diff_summary=preview.get("diff", {}),
    )
