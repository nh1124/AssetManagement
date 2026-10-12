from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import Conflict, Invalid, NotFound, Refused
from ..domain.money import Money
from ..services.money_storage import money_client_currency
from ..services.fx_service import get_exchange_rate
from ..services import ai_change_request_store
from ..services.fx_service import get_client_currency
from ..services.ledger_service import (
    ensure_default_accounts,
    create_transaction,
    find_account_ids,
    propose_transaction,
    simple_legs,
)
from ..services.budget_plan_store import get_plan_line, update_plan_lines
from ..services.cache_service import invalidate_client
from ..services.capsule_service import apply_capsule_rules_for_transaction
from ..services.registry_service import get_recurring_transaction, upsert_registry_from_recurring_payload
from ..services.ai_policy_service import (
    AiOperationContext,
    evaluate_ai_operation,
    has_amount_threshold,
    ledger_write_is_direct,
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

RECURRING_TRANSACTION_FIELDS = [
    "id",
    "name",
    "amount",
    "currency",
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
    if parsed.currency is None:
        parsed.currency = get_client_currency(db, client_id)
    if parsed.amount <= 0:
        raise ValueError("Transaction amount must be positive")

    account_ids = [value for value in [parsed.from_account_id, parsed.to_account_id] if value is not None]
    if account_ids:
        found_ids = find_account_ids(db, client_id, account_ids)
        missing = [account_id for account_id in account_ids if account_id not in found_ids]
        if missing:
            raise ValueError(f"Account not found: {missing[0]}")

    return parsed.model_dump(mode="json")


def _validate_account_refs(db: Session, client_id: int, payload: dict[str, Any]) -> None:
    account_ids = [value for value in [payload.get("from_account_id"), payload.get("to_account_id")] if value is not None]
    if not account_ids:
        return
    found_ids = find_account_ids(db, client_id, account_ids)
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
    line = get_plan_line(db, client_id, line_id)
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
    if data.get("currency") is None:
        data["currency"] = get_client_currency(db, client_id)
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
    recurring = get_recurring_transaction(db, client_id, recurring_id)
    if not recurring:
        raise ValueError("Recurring transaction not found")
    data = schemas.RecurringTransactionCreate(**payload).model_dump(mode="json")
    if data["currency"] is None:
        data["currency"] = recurring.currency
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
        raise Invalid(f"Unsupported change request operation: {resource}:{action}")

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
        raise Invalid(str(exc)) from exc

    context = _operation_context(db, client_id, payload, resource, action, preview)
    decision = evaluate_ai_operation(db, client_id, context)
    if decision.decision == "denied":
        raise Refused(
            decision.reason,
            payload={
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
    existing = ai_change_request_store.find_by_idempotency_key(db, client_id, idempotency_key)
    if existing:
        return existing

    fields = dict(
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
    row = ai_change_request_store.create(db, client_id, fields, commit=False)

    context = _operation_context(db, client_id, payload, preview["resource"], preview["action"], preview)
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
        raise Invalid(f"Change request cannot be approved from status {row.status}")
    if row.requires_mfa:
        if not step_up_token_payload or step_up_token_payload.get("type") != "step_up" or str(step_up_token_payload.get("sub")) != str(actor_client_id):
            raise Refused("Step-up authentication required", status_code=401)
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
        raise Invalid(f"Change request cannot be rejected from status {row.status}")
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
    row = _get_change_request(db, client_id, change_request_id, for_update=True)
    if row.status == "applied":
        return row
    if row.status != "approved":
        raise Invalid(f"Change request must be approved before apply; current status is {row.status}")

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
    except ValueError as exc:
        db.rollback()
        failed_row = _get_change_request(db, client_id, change_request_id, for_update=True)
        if failed_row.status == "approved":
            failed_row.status = "failed"
            failed_row.result = {"error": "apply_failed", "message": str(exc)}
            failed_row.updated_at = datetime.utcnow()
            db.commit()
        raise Invalid(str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(row)
    invalidate_client(client_id)
    return row


def _apply_dispatch(db: Session, client_id: int, row: models.AiChangeRequest) -> dict[str, Any]:
    if (row.resource, row.action) == ("transactions", "create"):
        ensure_default_accounts(db, client_id=client_id, commit=False)
        data = schemas.TransactionCreate(**row.input_payload).model_dump()
        if data["currency"] is None:
            data["currency"] = get_client_currency(db, client_id)
        data["amount_minor"] = Money.from_major(str(data.pop("amount")), data["currency"]).minor
        legs = data.pop("legs", None)
        from_account_id = data.pop("from_account_id", None)
        to_account_id = data.pop("to_account_id", None)
        if legs is None:
            legs = simple_legs(data["amount_minor"], from_account_id, to_account_id)
        # mfa_verified stays False: nothing on the row proves a verification
        # happened, and row.requires_mfa says the opposite - that one was
        # demanded. A gate with no proof must stay shut, so a policy of
        # allow_execute plus require_mfa queues rather than posts.
        if not ledger_write_is_direct(
            db,
            client_id,
            ai_client_id=row.ai_client_id,
            risk=row.risk,
        ):
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
            raise ValueError("Monthly plan line id is required")
        payload = {**row.input_payload, "id": line_id}
        saved = update_plan_lines(db, client_id, [payload], commit=False)
        return {"ids": [line.id for line in saved]}

    if (row.resource, row.action) == ("recurring_transactions", "create"):
        data = schemas.RecurringTransactionCreate(**row.input_payload).model_dump()
        recurring = upsert_registry_from_recurring_payload(db, client_id, data)
        return {"recurring_transaction_id": recurring.id}

    if (row.resource, row.action) == ("recurring_transactions", "update"):
        recurring_id = int(row.target_ref.get("id") or row.input_payload.get("id") or 0)
        if not recurring_id:
            raise ValueError("Recurring transaction id is required")
        recurring = get_recurring_transaction(db, client_id, recurring_id)
        if not recurring:
            raise ValueError("Recurring transaction not found")
        data = schemas.RecurringTransactionUpdate(**row.input_payload).model_dump(exclude_unset=True)
        recurring = upsert_registry_from_recurring_payload(db, client_id, data, recurring)
        db.flush()
        return {"recurring_transaction_id": recurring.id}

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
        raise NotFound("Change request not found")
    return row


def _operation_context(
    db: Session,
    client_id: int,
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
        amount=_amount_from_payload(db, client_id, preview.get("input_payload", {}),
                                   resource=resource, action=action, risk=payload.risk, ai_client_id=payload.ai_client_id),
        count=_count_from_payload(preview.get("input_payload", {})),
    )


def _amount_from_payload(
    db: Session, client_id: int, payload: dict[str, Any], *,
    resource: str, action: str, risk: str, ai_client_id: int | None,
) -> int | None:
    amount = payload.get("amount")
    if type(amount) not in (int, float):
        return None
    currency = money_client_currency(db, client_id)
    source = payload.get("currency") or currency
    if source != currency:
        # A policy without an amount threshold needs no foreign-currency valuation.
        if not has_amount_threshold(db, client_id, resource=resource, action=action, risk=risk, ai_client_id=ai_client_id):
            return None
        as_of = date.fromisoformat(str(payload["date"])) if payload.get("date") else None
        rate = get_exchange_rate(db, client_id, source, currency, as_of)
        if rate is None:
            raise Invalid(f"Cannot compare AI threshold without an exchange rate for {source}/{currency}")
        # A policy is denominated in the client currency even for a foreign request.
        amount = Decimal(str(amount)) * Decimal(str(rate))
    return Money.from_major(str(amount), currency).minor


def _count_from_payload(payload: dict[str, Any]) -> int | None:
    if "lines" in payload and isinstance(payload["lines"], list):
        return len(payload["lines"])
    return 1
