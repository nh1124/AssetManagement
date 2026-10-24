from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session
from sqlalchemy import or_

from .money_storage import to_minor, money_client_currency

from .. import models
from ..domain.errors import Refused
from ..domain.messages import Message

AiRisk = Literal["low", "medium", "high", "critical"]
AiMode = Literal["deny", "allow_read", "require_approval", "allow_execute"]
AiDecision = Literal["allowed", "denied", "approval_required", "applied", "failed"]
AiSource = Literal["frontend", "mcp_http", "mcp_stdio", "backend"]

AI_OPERATION_RESOURCES = [
    "ai_context",
    "transactions",
    "accounts",
    "monthly_plan_lines",
    "budget_plans",
    "auto_transactions",
    "registry_entries",
    "products",
    "capsules",
    "life_events",
    "exchange_rates",
    "data_transfer",
    "data_export",
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
    "encrypted",
    "code_hash",
    "recovery_code",
    "refresh_token",
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
    amount: int | None = None
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


def ledger_write_is_direct(
    db: Session,
    client_id: int,
    *,
    ai_client_id: int | None,
    risk: str,
    mfa_verified: bool = False,
) -> bool:
    # Permission to bypass the ledger proposal queue differs from permission
    # for the AI to act at all, even after its change request is approved.
    decision = evaluate_ai_operation(
        db,
        client_id,
        AiOperationContext(
            resource="transactions",
            action="create",
            risk=normalize_risk(risk),
            ai_client_id=ai_client_id,
            mfa_verified=mfa_verified,
        ),
    )
    return decision.mode == "allow_execute" and decision.allowed


def assert_direct_ledger_write_allowed(
    db: Session,
    client_id: int,
    *,
    mcp_client_id: str | None,
    risk: str = "medium",
) -> None:
    # Skipping policy evaluation keeps a human's own write out of the AI gate.
    if not mcp_client_id:
        return
    if not ledger_write_is_direct(db, client_id, ai_client_id=None, risk=risk):
        # 403 rather than 409: the request does not conflict with the ledger's
        # state, the caller simply may not write it. Retrying changes nothing
        # until a human opens the policy, so the message names it.
        raise Refused(
            (
                "Direct MCP ledger write refused: the ai_operation_policies row for "
                f"transactions / create / {risk} must have mode allow_execute and "
                "have no unmet MFA requirement; otherwise use the change-request path."
            ),
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
        raise Refused(
            decision.reason,
            payload={
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
            threshold_amount_minor=to_minor(item.get("threshold_amount"), money_client_currency(db, client_id)),
            threshold_count=item.get("threshold_count"),
            require_mfa=bool(item.get("require_mfa", False)),
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def list_audit_logs(
    db: Session, client_id: int, *, limit: int, offset: int,
) -> list[models.AiAuditLog]:
    return db.query(models.AiAuditLog).filter(
        models.AiAuditLog.client_id == client_id,
    ).order_by(models.AiAuditLog.created_at.desc(), models.AiAuditLog.id.desc()).offset(offset).limit(limit).all()


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
    if policy.threshold_amount_minor is not None and context.amount is not None and context.amount < policy.threshold_amount_minor:
        return False
    if policy.threshold_count is not None and context.count is not None and context.count < policy.threshold_count:
        return False
    return True


def has_amount_threshold(db, client_id, *, resource, action, risk, ai_client_id):
    return db.query(models.AiOperationPolicy.id).filter(
        models.AiOperationPolicy.client_id == client_id,
        models.AiOperationPolicy.resource == resource,
        models.AiOperationPolicy.action == action,
        models.AiOperationPolicy.risk == risk,
        or_(models.AiOperationPolicy.ai_client_id.is_(None), models.AiOperationPolicy.ai_client_id == ai_client_id),
        models.AiOperationPolicy.threshold_amount_minor.is_not(None),
    ).first() is not None


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


# ─── WP34: every MCP request is an AI operation, audited and scoped ──────────
#
# The owner's rule (2026-10-24): every operation the AI makes through MCP is
# recorded here, whether it read, wrote directly or queued for approval, with
# what let it through. The administrator's request and db.change logs are a
# different record for a different reader.

AiAuthorization = Literal[
    "read", "direct_policy", "direct_mode", "change_request", "human_approved",
    "refused_scope", "refused_policy", "refused_mode", "failed",
]

# Rows in these tables mean the request wrote the ledger, which only the
# transactions/create policy row may allow directly (ai_write_path §1.6).
LEDGER_TABLES = frozenset({"transactions", "journal_entries"})
MAX_AUDITED_CHANGES = 200
MAX_REQUEST_BODY_CHARS = 4000
MAX_ERROR_CHARS = 1000
REFUSED_ERROR = "ai_operation_refused"

# What the AI may never do, whatever its policies and write mode say: change
# its own permissions, act on the account, or approve. Approval is a person's
# decision (owner 2026-10-24); applying what a person approved stays open.
_MCP_REFUSALS: tuple[tuple[str | None, re.Pattern, str], ...] = (
    ("PUT", re.compile(r"^/ai/(policies|execution-settings)/?$"), "ai_permissions"),
    ("POST", re.compile(r"^/ai/change-requests/\d+/(approve|reject)/?$"), "human_approval"),
    ("POST", re.compile(r"^/transactions/proposals/\d+/(approve|reject)/?$"), "human_approval"),
    (None, re.compile(r"^/auth(/|$)"), "account"),
)

REFUSAL_MESSAGES = {
    "ai_permissions": ("AI permissions are changed by a person in the app, not through MCP.",
                       "AI の権限（ポリシー・書き込み方式）は MCP からは変更できません。アプリで変更してください。"),
    "human_approval": ("Approving or rejecting is a person's decision; do it in the app.",
                       "承認・却下は人が行います。アプリで操作してください。"),
    "account": ("Account operations are not available through MCP.",
                "アカウントの操作は MCP からはできません。"),
    "change_request_mode": ("Writes go through change requests in this client's settings; create an AI change request instead.",
                            "この設定では書き込みは承認リクエスト経由です。承認リクエストを作成してください。"),
}

# Last path segments that name what a request does rather than what it acts on.
_ACTION_SEGMENTS = {
    "preview": "preview", "validate": "preview", "refresh-preview": "preview", "goal-preview": "preview",
    "evaluate": "evaluate", "approve": "approve", "apply": "apply", "reject": "reject",
    "adjust": "adjust", "run": "run", "contribute": "contribute", "drawdown": "drawdown",
    "duplicate": "duplicate", "import": "import", "auto-update": "update", "copy-period": "copy",
    "decision": "decide", "goal": "make_goal",
}
_LOW_RISK_ACTIONS = {"read", "preview", "evaluate"}
_HIGH_RISK_ACTIONS = {"delete", "import", "adjust"}


@dataclass
class McpRequestFacts:
    """One MCP request as the gateway saw it; also what a restore from the logs rebuilds."""
    method: str
    path: str
    status: int
    query: str = ""
    duration_ms: float | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    mcp_client_id: str | None = None
    tool_name: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    request_body: Any = None
    error: Any = None
    refusal: str | None = None
    changes: list[dict] = field(default_factory=list)
    created_at: datetime | None = None
    restored_from: str | None = None


def mcp_write_mode_of(general_settings: dict | None) -> str:
    ai_operation = (general_settings or {}).get("ai_operation")
    mode = ai_operation.get("mcp_write_mode") if isinstance(ai_operation, dict) else None
    return mode if mode in {"direct_write", "change_request"} else "direct_write"


def mcp_request_is_operation(method: str, path: str) -> bool:
    """False for MCP requests that are plumbing, not something the AI did."""
    if path.startswith("/health") or path.startswith("/auth/mcp/exchange"):
        return False
    # The MCP server asks for the write mode before every write it forwards.
    return not (method == "GET" and path.rstrip("/") == "/ai/execution-settings")


def _forwards_write(method: str, path: str) -> bool:
    # The same test the MCP server applies before it forwards a write (api-client.ts).
    if method in {"GET", "HEAD", "OPTIONS"}:
        return False
    if path.startswith(("/auth/", "/ai/change-requests", "/ai/execution-settings")) or path == "/ai/evaluate":
        return False
    return "/preview" not in path


def mcp_refusal(db: Session, client_id: int, method: str, path: str) -> str | None:
    """Why the AI may not make this request at all, or None. Checked before the endpoint runs."""
    for refused_method, pattern, reason in _MCP_REFUSALS:
        if (refused_method is None or refused_method == method) and pattern.match(path):
            return reason
    if _forwards_write(method, path):
        client = db.get(models.Client, client_id)
        if mcp_write_mode_of(client.general_settings if client else None) == "change_request":
            return "change_request_mode"
    return None


def mcp_refusal_error(reason: str) -> Refused:
    english, japanese = REFUSAL_MESSAGES[reason]
    return Refused(english, ja=japanese, payload={
        "error": REFUSED_ERROR,
        "reason": reason,
        "message": Message(english, ja=japanese),
    })


def describe_mcp_request(method: str, path: str) -> tuple[str, str, AiRisk, int | None]:
    """What a request acts on and does, from its method and path.

    /capsules/3/contribute -> ("capsules", "contribute"); /analysis/reconcile/40/adjust ->
    ("analysis.reconcile", "adjust"); GET /accounts/ -> ("accounts", "read"). The last
    number in the path is the target's id.
    """
    segments = [segment for segment in path.strip("/").split("/") if segment]
    target = next((int(segment) for segment in reversed(segments) if segment.isdigit()), None)
    names = [segment for segment in segments if not segment.isdigit()]
    action = {"GET": "read", "HEAD": "read", "POST": "create", "PUT": "update", "PATCH": "update",
              "DELETE": "delete"}.get(method, method.lower())
    if len(names) > 1 and names[-1] in _ACTION_SEGMENTS:
        action = _ACTION_SEGMENTS[names.pop()]
    resource = ".".join(name.replace("-", "_") for name in names[:3]) or "root"
    risk: AiRisk = "low" if action in _LOW_RISK_ACTIONS else "high" if action in _HIGH_RISK_ACTIONS else "medium"
    return resource, action, risk, target


def _error_payload(error: Any) -> dict:
    """An error response body as a dict; a structured detail ({"detail": {...}}) unwrapped."""
    if isinstance(error, (bytes, bytearray)):
        error = error.decode("utf-8", "replace")
    if isinstance(error, str) and error:
        try:
            error = json.loads(error)
        except ValueError:
            return {"text": error[:MAX_ERROR_CHARS]}
    if not isinstance(error, dict):
        return {"detail": error} if error not in (None, "") else {}
    detail = error.get("detail")
    return detail if isinstance(detail, dict) else error


def _authorize(
    db: Session, client_id: int, facts: McpRequestFacts, resource: str, action: str,
) -> tuple[AiAuthorization, AiDecision, dict]:
    """What let the request through or stopped it, and the facts that show it."""
    client = db.get(models.Client, client_id)
    write_mode = mcp_write_mode_of(client.general_settings if client else None)
    detail: dict[str, Any] = {"mcp_write_mode": write_mode}
    error = _error_payload(facts.error)
    refusal = facts.refusal or (error.get("reason") if error.get("error") == REFUSED_ERROR else None)
    if refusal:
        detail["refusal"] = refusal
        return ("refused_mode" if refusal == "change_request_mode" else "refused_scope"), "denied", detail
    if facts.status in {401, 403}:
        return "refused_policy", "denied", detail
    if facts.status >= 400:
        return "failed", "failed", detail
    if facts.method in {"GET", "HEAD"} or action in {"preview", "evaluate"}:
        return "read", "allowed", detail
    if resource == "ai.change_requests" and action == "create":
        return "change_request", "approval_required", detail
    if resource == "ai.change_requests" and action == "apply":
        # Only a person can approve (the refusals above), so an applied request was approved by one.
        return "human_approved", "applied", detail
    if any(change.get("table") in LEDGER_TABLES for change in facts.changes):
        gate = evaluate_ai_operation(db, client_id, AiOperationContext(resource="transactions", action="create", risk="medium"))
        detail["policy"] = {
            "id": gate.policy_id, "resource": "transactions", "action": "create", "risk": "medium",
            "mode": gate.mode, "require_mfa": gate.require_mfa,
        }
        return "direct_policy", "applied", detail
    return "direct_mode", "applied", detail


def _compact_changes(changes: list[dict]) -> dict:
    tables: dict[str, int] = {}
    for change in changes:
        tables[change.get("table", "?")] = tables.get(change.get("table", "?"), 0) + 1
    kept = [_redact(change, depth=1, max_depth=4) for change in changes[:MAX_AUDITED_CHANGES]]
    summary: dict[str, Any] = {"tables": tables, "changes": kept}
    if len(changes) > MAX_AUDITED_CHANGES:
        summary["omitted"] = len(changes) - MAX_AUDITED_CHANGES
    return summary


def _request_summary(facts: McpRequestFacts) -> dict:
    summary: dict[str, Any] = {"method": facts.method, "path": facts.path}
    if facts.query:
        summary["query"] = facts.query[:500]
    # Account requests carry credentials (passwords, authenticator codes): never kept.
    if facts.request_body not in (None, "", b"") and not facts.path.startswith("/auth"):
        body = facts.request_body
        if isinstance(body, (bytes, bytearray)):
            try:
                body = json.loads(body)
            except ValueError:
                body = {"text": body[:MAX_REQUEST_BODY_CHARS].decode("utf-8", "replace")}
        text = json.dumps(body, ensure_ascii=False, default=str)
        summary["body"] = redact_sensitive(body) if len(text) <= MAX_REQUEST_BODY_CHARS else {
            "truncated": True, "preview": text[:MAX_REQUEST_BODY_CHARS],
        }
    if facts.restored_from:
        summary["restored_from"] = facts.restored_from
    return summary


def record_mcp_operation(db: Session, client_id: int, facts: McpRequestFacts) -> list[models.AiAuditLog]:
    """Write the audit row for one MCP request, and commit.

    An endpoint that already wrote its own audit row (a change request, a context
    read) gets that row completed rather than a second one: one operation, one row.
    """
    resource, action, risk, target = describe_mcp_request(facts.method, facts.path)
    own_rows = [change.get("pk") for change in facts.changes
                if change.get("table") == "ai_audit_logs" and change.get("op") == "insert"]
    changes = [change for change in facts.changes if change.get("table") != "ai_audit_logs"]
    facts = replace(facts, changes=changes)
    authorization, decision, detail = _authorize(db, client_id, facts, resource, action)
    result: dict[str, Any] = {"status": facts.status, "authorization": detail}
    if facts.duration_ms is not None:
        result["duration_ms"] = facts.duration_ms
    error = _error_payload(facts.error)
    if error:
        result["error"] = redact_sensitive(error)
    http = {
        "authorization": authorization, "http_status": facts.status,
        "request_id": facts.request_id, "correlation_id": facts.correlation_id,
    }
    rows = db.query(models.AiAuditLog).filter(
        models.AiAuditLog.client_id == client_id, models.AiAuditLog.id.in_(own_rows),
    ).all() if own_rows else []
    for row in rows:
        for key, value in http.items():
            setattr(row, key, value)
        row.request_summary = {**(row.request_summary or {}), "http": _request_summary(facts)}
        row.result_summary = {**(row.result_summary or {}), **result}
        if changes:
            row.diff_summary = {**(row.diff_summary or {}), **_compact_changes(changes)}
    if not rows:
        approval_request_id = target if resource == "ai.change_requests" and action == "apply" else None
        row = models.AiAuditLog(
            client_id=client_id,
            actor_client_id=client_id,
            mcp_client_id=facts.mcp_client_id,
            source="mcp_http",
            tool_name=facts.tool_name,
            resource=resource,
            action=action,
            risk=risk,
            decision=decision,
            request_summary=_request_summary(facts),
            diff_summary=_compact_changes(changes) if changes else {},
            result_summary=result,
            approval_request_id=approval_request_id,
            ip_address=facts.ip_address,
            user_agent=(facts.user_agent or "")[:200] or None,
            **http,
            **({"created_at": facts.created_at} if facts.created_at else {}),
        )
        db.add(row)
        rows = [row]
    db.commit()
    return rows


def audited_request_ids(db: Session, client_id: int, request_ids: list[str]) -> set[str]:
    """The request ids among these that already have an audit row (the restore skips them)."""
    if not request_ids:
        return set()
    found = db.query(models.AiAuditLog.request_id).filter(
        models.AiAuditLog.client_id == client_id, models.AiAuditLog.request_id.in_(request_ids),
    ).all()
    return {request_id for (request_id,) in found}
