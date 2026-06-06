from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..services.accounting_service import ensure_default_accounts, process_transaction
from ..services.budget_plan_service import update_plan_lines
from ..services.cache_service import invalidate_client
from ..services.capsule_service import apply_capsule_rules_for_transaction
from ..services.ai_policy_service import (
    AiOperationContext,
    evaluate_ai_operation,
    write_ai_audit_log,
)


SUPPORTED_OPERATIONS = {
    ("transactions", "create"),
    ("monthly_plan_lines", "update"),
    ("recurring_transactions", "create"),
    ("recurring_transactions", "update"),
}


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


TRANSACTION_FIELDS = [
    "id",
    "date",
    "description",
    "amount",
    "type",
    "category",
    "currency",
    "from_account_id",
    "to_account_id",
    "batch_id",
]

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
    "source_id",
    "identity_key",
    "manual_override",
    "cash_treatment",
    "recurring_transaction_id",
    "is_active",
    "plan_id",
]

RECURRING_TRANSACTION_FIELDS = [
    "id",
    "name",
    "amount",
    "currency",
    "type",
    "from_account_id",
    "to_account_id",
    "frequency",
    "day_of_month",
    "month_of_year",
    "next_due_date",
    "start_period",
    "end_period",
    "auto_post",
    "is_active",
    "source_registry_entry_id",
]


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
    if parsed.amount <= 0:
        raise ValueError("Transaction amount must be positive")

    account_ids = [value for value in [parsed.from_account_id, parsed.to_account_id] if value is not None]
    if account_ids:
        found = db.query(models.Account.id).filter(
            models.Account.client_id == client_id,
            models.Account.id.in_(account_ids),
        ).all()
        found_ids = {row[0] for row in found}
        missing = [account_id for account_id in account_ids if account_id not in found_ids]
        if missing:
            raise ValueError(f"Account not found: {missing[0]}")

    return parsed.model_dump(mode="json")


def _validate_account_refs(db: Session, client_id: int, payload: dict[str, Any]) -> None:
    account_ids = [value for value in [payload.get("from_account_id"), payload.get("to_account_id")] if value is not None]
    if not account_ids:
        return
    found = db.query(models.Account.id).filter(
        models.Account.client_id == client_id,
        models.Account.id.in_(account_ids),
    ).all()
    found_ids = {row[0] for row in found}
    missing = [account_id for account_id in account_ids if account_id not in found_ids]
    if missing:
        raise ValueError(f"Account not found: {missing[0]}")


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
        raise ValueError("Monthly plan line id is required")
    line = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.id == line_id,
        models.MonthlyPlanLine.client_id == client_id,
    ).first()
    if not line:
        raise ValueError("Monthly plan line not found")

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


def _preview_recurring_create(db: Session, client_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = schemas.RecurringTransactionUpdate(**payload).model_dump(exclude_unset=True, mode="json")
    if "amount" in data and data["amount"] is not None and data["amount"] <= 0:
        raise ValueError("Recurring transaction amount must be positive")
    _validate_account_refs(db, client_id, data)
    after = dict(data)
    after["id"] = None
    return {
        "target_ref": {"resource": "recurring_transactions"},
        "input_payload": data,
        "before_snapshot": {},
        "after_snapshot": after,
        "diff": _diff({}, after),
        "validation": {"valid": True, "messages": []},
        "precondition_hash": _stable_hash({}),
    }


def _preview_recurring_update(db: Session, client_id: int, target_ref: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    recurring_id = int(target_ref.get("id") or payload.get("id") or 0)
    if not recurring_id:
        raise ValueError("Recurring transaction id is required")
    recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == client_id,
    ).first()
    if not recurring:
        raise ValueError("Recurring transaction not found")
    data = schemas.RecurringTransactionCreate(**payload).model_dump(mode="json")
    if data["amount"] <= 0:
        raise ValueError("Recurring transaction amount must be positive")
    _validate_account_refs(db, client_id, data)
    before = _model_dict(recurring, RECURRING_TRANSACTION_FIELDS)
    after = {**before, **data, "id": recurring_id}
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
        raise HTTPException(status_code=400, detail=f"Unsupported change request operation: {resource}:{action}")

    try:
        if (resource, action) == ("transactions", "create"):
            preview = _preview_transaction_create(db, client_id, payload.input_payload)
        elif (resource, action) == ("monthly_plan_lines", "update"):
            preview = _preview_monthly_plan_lines_update(db, client_id, payload.target_ref, payload.input_payload)
        elif (resource, action) == ("recurring_transactions", "create"):
            preview = _preview_recurring_create(db, client_id, payload.input_payload)
        else:
            preview = _preview_recurring_update(db, client_id, payload.target_ref, payload.input_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    context = _operation_context(payload, resource, action, preview)
    decision = evaluate_ai_operation(db, client_id, context)
    if decision.decision == "denied":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ai_operation_denied",
                "resource": decision.resource,
                "action": decision.action,
                "risk": decision.risk,
                "reason": decision.reason,
            },
        )
    requires_mfa = decision.require_mfa or decision.risk == "critical"
    return {
        "resource": resource,
        "action": action,
        "risk": decision.risk,
        "requires_mfa": requires_mfa,
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
    existing = db.query(models.AiChangeRequest).filter(
        models.AiChangeRequest.client_id == client_id,
        models.AiChangeRequest.idempotency_key == idempotency_key,
    ).first()
    if existing:
        return existing

    row = models.AiChangeRequest(
        client_id=client_id,
        created_by_client_id=actor_client_id,
        ai_client_id=payload.ai_client_id,
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
        requires_mfa=preview["requires_mfa"],
        expires_at=payload.expires_at,
        result={},
    )
    db.add(row)
    db.flush()

    context = _operation_context(payload, preview["resource"], preview["action"], preview)
    decision = evaluate_ai_operation(db, client_id, context)
    log = write_ai_audit_log(
        db,
        client_id,
        context,
        decision,
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
    query = db.query(models.AiChangeRequest).filter(models.AiChangeRequest.client_id == client_id)
    if status_filter:
        query = query.filter(models.AiChangeRequest.status == status_filter)
    return query.order_by(models.AiChangeRequest.created_at.desc(), models.AiChangeRequest.id.desc()).offset(offset).limit(limit).all()


def approve_change_request(
    db: Session,
    client_id: int,
    actor_client_id: int,
    change_request_id: int,
    step_up_token_payload: dict[str, Any] | None = None,
) -> models.AiChangeRequest:
    row = _get_change_request(db, client_id, change_request_id)
    if row.status not in {"draft", "pending"}:
        raise HTTPException(status_code=400, detail=f"Change request cannot be approved from status {row.status}")
    if row.requires_mfa:
        if not step_up_token_payload or step_up_token_payload.get("type") != "step_up" or str(step_up_token_payload.get("sub")) != str(actor_client_id):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Step-up authentication required")
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
        raise HTTPException(status_code=400, detail=f"Change request cannot be rejected from status {row.status}")
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
    row = _get_change_request(db, client_id, change_request_id)
    preview_payload = schemas.AiChangeRequestPreviewRequest(
        source=row.source,
        tool_name=row.tool_name,
        resource=row.resource,
        action=row.action,
        risk=row.risk,
        ai_client_id=row.ai_client_id,
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
    row.requires_mfa = preview["requires_mfa"]
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
    row = _get_change_request(db, client_id, change_request_id)
    if row.status == "applied":
        return row
    if row.status != "approved":
        raise HTTPException(status_code=400, detail=f"Change request must be approved before apply; current status is {row.status}")

    current_preview = preview_change_request(
        db,
        client_id,
        schemas.AiChangeRequestPreviewRequest(
            source=row.source,
            tool_name=row.tool_name,
            resource=row.resource,
            action=row.action,
            risk=row.risk,
            ai_client_id=row.ai_client_id,
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
        raise HTTPException(status_code=409, detail=row.result)

    try:
        result = _apply_dispatch(db, client_id, row)
    except ValueError as exc:
        row.status = "failed"
        row.result = {"error": "apply_failed", "message": str(exc)}
        row.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        ai_client_id=row.ai_client_id,
        mcp_client_id=row.mcp_client_id,
        request_summary=row.input_payload,
        diff_summary=row.diff,
        mfa_verified=row.requires_mfa,
    )
    decision = evaluate_ai_operation(db, client_id, context)
    log = write_ai_audit_log(
        db,
        client_id,
        context,
        decision,
        result={"change_request_id": row.id, "status": row.status, **result},
        commit=False,
    )
    log.approval_request_id = row.id
    db.commit()
    db.refresh(row)
    return row


def _apply_dispatch(db: Session, client_id: int, row: models.AiChangeRequest) -> dict[str, Any]:
    if (row.resource, row.action) == ("transactions", "create"):
        ensure_default_accounts(db, client_id=client_id)
        data = schemas.TransactionCreate(**row.input_payload).model_dump()
        tx = models.Transaction(**data, client_id=client_id)
        db.add(tx)
        db.flush()
        process_transaction(db, tx)
        db.flush()
        apply_capsule_rules_for_transaction(db, tx)
        invalidate_client(client_id)
        return {"transaction_id": tx.id}

    if (row.resource, row.action) == ("monthly_plan_lines", "update"):
        line_id = int(row.target_ref.get("id") or row.input_payload.get("id") or 0)
        if not line_id:
            raise ValueError("Monthly plan line id is required")
        payload = {**row.input_payload, "id": line_id}
        saved = update_plan_lines(db, client_id, [payload])
        invalidate_client(client_id)
        return {"ids": [line.id for line in saved]}

    if (row.resource, row.action) == ("recurring_transactions", "create"):
        data = schemas.RecurringTransactionCreate(**row.input_payload).model_dump()
        recurring = models.RecurringTransaction(**data, client_id=client_id)
        db.add(recurring)
        db.flush()
        invalidate_client(client_id)
        return {"recurring_transaction_id": recurring.id}

    if (row.resource, row.action) == ("recurring_transactions", "update"):
        recurring_id = int(row.target_ref.get("id") or row.input_payload.get("id") or 0)
        if not recurring_id:
            raise ValueError("Recurring transaction id is required")
        recurring = db.query(models.RecurringTransaction).filter(
            models.RecurringTransaction.id == recurring_id,
            models.RecurringTransaction.client_id == client_id,
        ).first()
        if not recurring:
            raise ValueError("Recurring transaction not found")
        data = schemas.RecurringTransactionUpdate(**row.input_payload).model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(recurring, key, value)
        db.flush()
        invalidate_client(client_id)
        return {"recurring_transaction_id": recurring.id}

    raise ValueError(f"Unsupported change request operation: {row.resource}:{row.action}")


def _get_change_request(db: Session, client_id: int, change_request_id: int) -> models.AiChangeRequest:
    row = db.query(models.AiChangeRequest).filter(
        models.AiChangeRequest.id == change_request_id,
        models.AiChangeRequest.client_id == client_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Change request not found")
    return row


def _operation_context(
    payload: schemas.AiChangeRequestPreviewRequest | schemas.AiChangeRequestCreate,
    resource: str,
    action: str,
    preview: dict[str, Any],
) -> AiOperationContext:
    return AiOperationContext(
        source=payload.source,
        tool_name=payload.tool_name,
        resource=resource,
        action=action,
        risk=payload.risk,
        ai_client_id=payload.ai_client_id,
        mcp_client_id=payload.mcp_client_id,
        request_summary=preview.get("input_payload", {}),
        diff_summary=preview.get("diff", {}),
        mfa_verified=payload.mfa_verified,
        amount=_amount_from_payload(preview.get("input_payload", {})),
        count=_count_from_payload(preview.get("input_payload", {})),
    )


def _amount_from_payload(payload: dict[str, Any]) -> float | None:
    amount = payload.get("amount")
    return float(amount) if isinstance(amount, (int, float)) else None


def _count_from_payload(payload: dict[str, Any]) -> int | None:
    if "lines" in payload and isinstance(payload["lines"], list):
        return len(payload["lines"])
    return 1
