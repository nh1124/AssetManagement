from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.ai_policy_service import (
    AiOperationContext,
    evaluate_ai_operation,
    list_client_policies,
    replace_client_policies,
    write_ai_audit_log,
)


router = APIRouter(prefix="/ai", tags=["ai-operations"])


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


@router.post("/evaluate", response_model=schemas.AiOperationEvaluateResponse)
def evaluate_ai_operation_api(
    payload: schemas.AiOperationEvaluateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    context = AiOperationContext(
        source=payload.source,
        tool_name=payload.tool_name,
        resource=payload.resource,
        action=payload.action,
        risk=payload.risk,
        ai_client_id=payload.ai_client_id,
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
