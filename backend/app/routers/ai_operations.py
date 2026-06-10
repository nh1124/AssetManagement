from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.ai_context_service import (
    get_context_resource,
    get_context_summary,
    list_context_resources,
)
from ..services.ai_policy_service import (
    AiOperationDecision,
    AiOperationContext,
    evaluate_ai_operation,
    list_client_policies,
    replace_client_policies,
    write_ai_audit_log,
)


router = APIRouter(prefix="/ai", tags=["ai-operations"])

SUPPORTED_CHANGE_REQUEST_OPERATIONS = [
    "transactions:create",
    "monthly_plan_lines:update",
    "recurring_transactions:create",
    "recurring_transactions:update",
]


def _execution_settings_payload(current_client: models.Client) -> dict:
    general = current_client.general_settings or {}
    ai_operation = general.get("ai_operation") if isinstance(general.get("ai_operation"), dict) else {}
    mode = ai_operation.get("mcp_write_mode") or "direct_write"
    if mode not in {"direct_write", "change_request"}:
        mode = "direct_write"
    return {
        "mcp_write_mode": mode,
        "supported_change_request_operations": SUPPORTED_CHANGE_REQUEST_OPERATIONS,
    }


@router.get("/policies", response_model=list[schemas.AiOperationPolicy])
def get_ai_policies(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return list_client_policies(db, current_client.id)


@router.put("/policies", response_model=list[schemas.AiOperationPolicy])
def put_ai_policies(
    policies: list[schemas.AiOperationPolicyCreate],
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return replace_client_policies(
        db,
        current_client.id,
        [policy.model_dump() for policy in policies],
    )


@router.get("/execution-settings", response_model=schemas.AiExecutionSettings)
def get_ai_execution_settings(
    current_client: models.Client = Depends(get_current_client),
):
    return _execution_settings_payload(current_client)


@router.put("/execution-settings", response_model=schemas.AiExecutionSettings)
def put_ai_execution_settings(
    payload: schemas.AiExecutionSettings,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    settings = dict(current_client.general_settings or {})
    ai_operation = dict(settings.get("ai_operation") or {})
    ai_operation["mcp_write_mode"] = payload.mcp_write_mode
    settings["ai_operation"] = ai_operation
    current_client.general_settings = settings
    flag_modified(current_client, "general_settings")
    db.commit()
    db.refresh(current_client)
    return _execution_settings_payload(current_client)


@router.get("/audit-logs", response_model=list[schemas.AiAuditLog])
def get_ai_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return db.query(models.AiAuditLog).filter(
        models.AiAuditLog.client_id == current_client.id,
    ).order_by(models.AiAuditLog.created_at.desc(), models.AiAuditLog.id.desc()).offset(offset).limit(limit).all()


@router.get("/context/resources", response_model=list[schemas.AiContextResourceDescriptor])
def get_ai_context_resources(
    request: Request,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    context, decision = _ensure_context_read_allowed(db, current_client, request, "resources")
    data = list_context_resources()
    _write_context_read_audit(db, current_client, context, decision, {"count": len(data)})
    return data


@router.get("/context/summary", response_model=schemas.AiContextResponse)
def get_ai_context_summary(
    request: Request,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    context, decision = _ensure_context_read_allowed(db, current_client, request, "summary")
    data = get_context_summary(db, current_client.id)
    _write_context_read_audit(db, current_client, context, decision, {"resource": "summary"})
    return data


@router.get("/context/resource/{resource}", response_model=schemas.AiContextResponse)
def get_ai_context_resource(
    resource: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    period: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    context, decision = _ensure_context_read_allowed(
        db,
        current_client,
        request,
        resource,
        limit=limit,
        period=period,
    )
    try:
        data = get_context_resource(db, current_client.id, resource, limit=limit, period=period)
    except HTTPException as exc:
        _write_context_read_audit(
            db,
            current_client,
            context,
            decision,
            {"error": exc.detail, "status_code": exc.status_code},
        )
        raise
    _write_context_read_audit(
        db,
        current_client,
        context,
        decision,
        {"resource": data["resource"], "classification": data["classification"]},
    )
    return data


@router.post("/evaluate", response_model=schemas.AiOperationEvaluateResponse)
def evaluate_ai_operation_api(
    payload: schemas.AiOperationEvaluateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    mcp_client_id = payload.mcp_client_id or request.headers.get("x-mcp-client-id")
    tool_name = payload.tool_name or request.headers.get("x-mcp-tool-name")
    source = "mcp_http" if mcp_client_id and payload.source == "backend" else payload.source
    context = AiOperationContext(
        source=source,
        tool_name=tool_name,
        resource=payload.resource,
        action=payload.action,
        risk=payload.risk,
        ai_client_id=payload.ai_client_id,
        mcp_client_id=mcp_client_id,
        request_summary=payload.request_summary,
        diff_summary=payload.diff_summary,
        mfa_verified=payload.mfa_verified,
        ip_address=payload.ip_address or (request.client.host if request.client else None),
        user_agent=payload.user_agent or request.headers.get("user-agent"),
    )
    decision = evaluate_ai_operation(db, current_client.id, context)
    write_ai_audit_log(db, current_client.id, context, decision, result={"decision": decision.decision})
    return {
        "decision": decision.decision,
        "mode": decision.mode,
        "resource": decision.resource,
        "action": decision.action,
        "risk": decision.risk,
        "require_mfa": decision.require_mfa,
        "reason": decision.reason,
    }


def _ensure_context_read_allowed(
    db: Session,
    current_client: models.Client,
    request: Request,
    context_resource: str,
    *,
    limit: int | None = None,
    period: str | None = None,
) -> tuple[AiOperationContext, AiOperationDecision]:
    mcp_client_id = request.headers.get("x-mcp-client-id")
    source = "mcp_http" if mcp_client_id else "backend"
    context = AiOperationContext(
        source=source,
        tool_name=request.headers.get("x-mcp-tool-name"),
        resource="ai_context",
        action="read",
        risk="low",
        mcp_client_id=mcp_client_id,
        request_summary={
            "context_resource": context_resource,
            "limit": limit,
            "period": period,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    decision = evaluate_ai_operation(db, current_client.id, context)
    if decision.decision != "allowed":
        write_ai_audit_log(
            db,
            current_client.id,
            context,
            decision,
            result={"decision": decision.decision, "reason": decision.reason},
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ai_context_read_not_allowed",
                "decision": decision.decision,
                "resource": decision.resource,
                "reason": decision.reason,
            },
        )
    return context, decision


def _write_context_read_audit(
    db: Session,
    current_client: models.Client,
    context: AiOperationContext,
    decision: AiOperationDecision,
    result: dict,
) -> None:
    write_ai_audit_log(db, current_client.id, context, decision, result=result)
