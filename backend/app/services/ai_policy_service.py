from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models

AiRisk = Literal["low", "medium", "high", "critical"]
AiMode = Literal["deny", "allow_read", "require_approval", "allow_execute"]
AiDecision = Literal["allowed", "denied", "approval_required", "applied", "failed"]
AiSource = Literal["frontend", "mcp_http", "mcp_stdio", "backend"]

AI_OPERATION_RESOURCES = [
    "transactions",
    "accounts",
    "monthly_plan_lines",
    "budget_plans",
    "recurring_transactions",
    "registry_entries",
    "products",
    "capsules",
    "life_events",
    "milestones",
    "exchange_rates",
    "data_transfer",
    "client_settings",
    "ai_settings",
    "mfa_settings",
]

READ_ACTIONS = {"read", "list", "get", "preview", "analyze", "suggest", "optimize"}
WRITE_ACTIONS = {"create", "update", "patch", "save", "apply", "delete", "import", "replace", "execute"}
SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "recovery_code",
    "totp",
    "otpauth",
)


@dataclass
class AiOperationContext:
    source: AiSource = "backend"
    tool_name: str | None = None
    resource: str = ""
    action: str = ""
    risk: AiRisk = "low"
    ai_client_id: int | None = None
    mcp_client_id: str | None = None
    request_summary: dict[str, Any] = field(default_factory=dict)
    diff_summary: dict[str, Any] = field(default_factory=dict)
    mfa_verified: bool = False
    ip_address: str | None = None
    user_agent: str | None = None
    amount: float | None = None
    count: int | None = None


@dataclass
class AiOperationDecision:
    decision: AiDecision
    mode: AiMode
    resource: str
    action: str
    risk: AiRisk
    require_mfa: bool = False
    reason: str = ""
    policy_id: int | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "allowed"


def normalize_resource(value: str) -> str:
    return (value or "").strip().lower()


def normalize_action(value: str) -> str:
    return (value or "").strip().lower()


def normalize_risk(value: str) -> AiRisk:
    normalized = (value or "low").strip().lower()
    if normalized not in {"low", "medium", "high", "critical"}:
        return "low"
    return normalized  # type: ignore[return-value]


def default_policy_for(resource: str, action: str, risk: str) -> tuple[AiMode, bool, str]:
    normalized_action = normalize_action(action)
    normalized_risk = normalize_risk(risk)

    if normalized_action in READ_ACTIONS:
        return "allow_read", False, "Read and preview operations are allowed by default"
    if normalized_risk == "critical":
        return "require_approval", True, "Critical AI operations require approval and MFA by default"
    if normalized_risk in {"medium", "high"} or normalized_action in WRITE_ACTIONS:
        return "require_approval", False, "AI write operations require approval by default"
    return "allow_execute", False, "Low-risk AI operation is allowed by default"


def evaluate_ai_operation(
    db: Session,
    client_id: int,
    context: AiOperationContext,
) -> AiOperationDecision:
    resource = normalize_resource(context.resource)
    action = normalize_action(context.action)
    risk = normalize_risk(context.risk)
    policy = _find_policy(db, client_id, context.ai_client_id, resource, action, risk, context)

    if policy:
        mode = policy.mode
        require_mfa = bool(policy.require_mfa)
        reason = f"Matched policy {policy.id}"
        policy_id = policy.id
    else:
        mode, require_mfa, reason = default_policy_for(resource, action, risk)
        policy_id = None

    decision = _decision_from_mode(mode=mode, action=action, require_mfa=require_mfa, mfa_verified=context.mfa_verified)
    return AiOperationDecision(
        decision=decision,
        mode=mode,  # type: ignore[arg-type]
        resource=resource,
        action=action,
        risk=risk,
        require_mfa=require_mfa,
        reason=reason,
        policy_id=policy_id,
    )


def write_ai_audit_log(
    db: Session,
    client_id: int,
    context: AiOperationContext,
    decision: AiOperationDecision,
    result: dict[str, Any] | None = None,
    commit: bool = True,
) -> models.AiAuditLog:
    log = models.AiAuditLog(
        client_id=client_id,
        actor_client_id=client_id,
        ai_client_id=context.ai_client_id,
        mcp_client_id=context.mcp_client_id,
        source=context.source,
        tool_name=context.tool_name,
        resource=decision.resource,
        action=decision.action,
        risk=decision.risk,
        decision=decision.decision,
        request_summary=redact_sensitive(context.request_summary),
        diff_summary=redact_sensitive(context.diff_summary),
        result_summary=redact_sensitive(result or {}),
        approval_request_id=None,
        mfa_verified=context.mfa_verified,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    else:
        db.flush()
    return log


def ensure_ai_operation_allowed(
    db: Session,
    client_id: int,
    context: AiOperationContext,
) -> AiOperationDecision:
    decision = evaluate_ai_operation(db, client_id, context)
    if decision.decision != "allowed":
        write_ai_audit_log(db, client_id, context, decision)
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ai_operation_not_allowed",
                "decision": decision.decision,
                "resource": decision.resource,
                "action": decision.action,
                "risk": decision.risk,
                "require_mfa": decision.require_mfa,
                "reason": decision.reason,
            },
        )
    return decision


def replace_client_policies(
    db: Session,
    client_id: int,
    policies: list[dict[str, Any]],
) -> list[models.AiOperationPolicy]:
    db.query(models.AiOperationPolicy).filter(models.AiOperationPolicy.client_id == client_id).delete()
    rows: list[models.AiOperationPolicy] = []
    for item in policies:
        row = models.AiOperationPolicy(
            client_id=client_id,
            ai_client_id=item.get("ai_client_id"),
            resource=normalize_resource(item["resource"]),
            action=normalize_action(item["action"]),
            risk=normalize_risk(item["risk"]),
            mode=item["mode"],
            threshold_amount=item.get("threshold_amount"),
            threshold_count=item.get("threshold_count"),
            require_mfa=bool(item.get("require_mfa", False)),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def list_client_policies(db: Session, client_id: int) -> list[models.AiOperationPolicy]:
    return db.query(models.AiOperationPolicy).filter(
        models.AiOperationPolicy.client_id == client_id,
    ).order_by(models.AiOperationPolicy.resource, models.AiOperationPolicy.action, models.AiOperationPolicy.risk).all()


def redact_sensitive(value: Any, *, max_depth: int = 4) -> Any:
    return _redact(value, depth=0, max_depth=max_depth)


def _find_policy(
    db: Session,
    client_id: int,
    ai_client_id: int | None,
    resource: str,
    action: str,
    risk: str,
    context: AiOperationContext,
) -> models.AiOperationPolicy | None:
    candidates = db.query(models.AiOperationPolicy).filter(
        models.AiOperationPolicy.client_id == client_id,
        models.AiOperationPolicy.resource == resource,
        models.AiOperationPolicy.action == action,
        models.AiOperationPolicy.risk == risk,
    ).all()

    applicable = [
        policy for policy in candidates
        if policy.ai_client_id in (None, ai_client_id)
        and _threshold_applies(policy, context)
    ]
    applicable.sort(key=lambda policy: 0 if policy.ai_client_id is None else 1, reverse=True)
    return applicable[0] if applicable else None


def _threshold_applies(policy: models.AiOperationPolicy, context: AiOperationContext) -> bool:
    if policy.threshold_amount is not None and context.amount is not None and context.amount < policy.threshold_amount:
        return False
    if policy.threshold_count is not None and context.count is not None and context.count < policy.threshold_count:
        return False
    return True


def _decision_from_mode(mode: str, action: str, require_mfa: bool, mfa_verified: bool) -> AiDecision:
    if mode == "deny":
        return "denied"
    if require_mfa and not mfa_verified and mode == "allow_execute":
        return "denied"
    if mode == "allow_read":
        return "allowed" if action in READ_ACTIONS else "denied"
    if mode == "allow_execute":
        return "allowed"
    if mode == "require_approval":
        return "approval_required"
    return "denied"


def _redact(value: Any, *, depth: int, max_depth: int) -> Any:
    if depth > max_depth:
        return "[truncated]"
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "...[truncated]"
    if isinstance(value, list):
        items = value[:25]
        redacted = [_redact(item, depth=depth + 1, max_depth=max_depth) for item in items]
        if len(value) > len(items):
            redacted.append(f"...[{len(value) - len(items)} more]")
        return redacted
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:50]:
            key_text = str(key)
            if _is_sensitive_key(key_text):
                result[key_text] = "[redacted]"
            else:
                result[key_text] = _redact(item, depth=depth + 1, max_depth=max_depth)
        if len(value) > 50:
            result["..."] = f"[{len(value) - 50} more]"
        return result
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)
