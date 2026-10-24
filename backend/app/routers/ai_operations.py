from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..database import get_db
from ..dependencies import get_current_client, mcp_client_id as request_mcp_client_id, request_language
from ..domain.errors import NotFound, Refused, detail_for, status_for
from ..services import mcp_connection_service
from ..utils.jwt import token_is_current
from ..services.ai_context_service import (
    get_context_resource,
    get_context_summary,
    list_context_resources,
)
from ..services.ai_policy_service import (
    AiOperationDecision,
    AiOperationContext,
    evaluate_ai_operation,
    list_audit_logs,
    list_client_policies,
    mcp_write_mode_of,
    replace_client_policies,
    write_ai_audit_log,
)
from ..services.client_settings_service import merge_ai_execution_settings


router = APIRouter(prefix="/ai", tags=["ai-operations"])

SUPPORTED_CHANGE_REQUEST_OPERATIONS = [
    "transactions:create",
    "monthly_plan_lines:update",
    "auto_transactions:create",
    "auto_transactions:update",
]


def _execution_settings_payload(current_client: models.Client) -> dict:
    return {
        "mcp_write_mode": mcp_write_mode_of(current_client.general_settings),
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
    merge_ai_execution_settings(db, current_client, {"mcp_write_mode": payload.mcp_write_mode})
    return _execution_settings_payload(current_client)


def _mcp_url() -> str:
    base = (settings.mcp_base_url or "").strip().rstrip("/") or next(iter(settings.allowed_mcp_token_issuers), "")
    return f"{base}/mcp" if base else ""


def _host(url: str) -> str | None:
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def _connection_payload(row: models.McpConnection, current_client: models.Client) -> dict:
    current = token_is_current({"auth_time_ms": row.auth_time_ms}, current_client.tokens_valid_after,
                               claim="auth_time_ms", required=True)
    return {
        "id": row.id,
        "client_name": row.client_name,
        "oauth_client_id": row.oauth_client_id,
        "client_source": row.client_source,
        "client_host": _host(row.oauth_client_id) if row.client_source == "cimd" else None,
        "redirect_host": _host(row.redirect_uri),
        "scope": row.scope,
        "connected_at": row.activated_at,
        "last_used_at": row.last_used_at,
        "expires_at": row.expires_at,
        "refreshable": row.allow_refresh,
        "status": "active" if current else "reconnect_required",
    }


@router.get("/mcp/connections", response_model=schemas.McpConnections)
def get_mcp_connections(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """The AI apps this person connected over MCP, and the address to connect another (WP35)."""
    rows = mcp_connection_service.list_connections(db, current_client.id)
    return {"mcp_url": _mcp_url(), "connections": [_connection_payload(row, current_client) for row in rows]}


@router.delete("/mcp/connections/{connection_id}", status_code=204)
def delete_mcp_connection(
    connection_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """End one connection: the app's next tool call is refused and its refresh token stops working."""
    try:
        mcp_connection_service.revoke(db, current_client.id, connection_id)
    except NotFound as error:
        raise HTTPException(status_code=status_for(error), detail=detail_for(error, request_language(request)))
    return Response(status_code=204)


@router.get("/audit-logs", response_model=list[schemas.AiAuditLog])
def get_ai_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return list_audit_logs(db, current_client.id, limit=limit, offset=offset)


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
    except (NotFound, Refused) as exc:
        _write_context_read_audit(
            db,
            current_client,
            context,
            decision,
            {"error": detail_for(exc), "status_code": status_for(exc)},
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
    # The token-bound client wins over whatever the payload names (WP34).
    mcp_client_id = request_mcp_client_id() or payload.mcp_client_id
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
    mcp_client_id = request_mcp_client_id()
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
