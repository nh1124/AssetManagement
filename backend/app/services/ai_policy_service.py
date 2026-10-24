from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from .. import models
from ..domain import ai_operations
from ..domain.ai_operations import AiMode, AiOperation
from ..domain.errors import Conflict, Invalid, NotFound, Refused
from ..domain.messages import Message

AiRisk = Literal["low", "medium", "high", "critical"]
AiDecision = Literal["allowed", "denied", "approval_required", "applied", "failed"]
AiSource = Literal["frontend", "mcp_http", "mcp_stdio", "backend"]

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
    mcp_client_id: str | None = None
    request_summary: dict[str, Any] = field(default_factory=dict)
    diff_summary: dict[str, Any] = field(default_factory=dict)
    mfa_verified: bool = False
    ip_address: str | None = None
    user_agent: str | None = None


# ─── WP36: one permission per operation ──────────────────────────────────────
#
# The person decides, for each operation in domain/ai_operations, whether the AI
# may do it directly (allow), only through a change request a person approves
# (approval), or not at all (deny). A row is saved only once the person sets it;
# until then the operation's default applies (owner 2026-10-24, C8).

def _saved_modes(db: Session, client_id: int) -> dict[str, AiMode]:
    rows = db.query(models.AiOperationPolicy).filter(models.AiOperationPolicy.client_id == client_id).all()
    return {row.operation: row.mode for row in rows if row.operation in ai_operations.BY_KEY}


def operation_mode(db: Session, client_id: int, key: str) -> AiMode:
    operation = ai_operations.BY_KEY[key]
    saved = db.query(models.AiOperationPolicy.mode).filter(
        models.AiOperationPolicy.client_id == client_id, models.AiOperationPolicy.operation == key,
    ).scalar()
    return saved if saved in operation.modes else operation.default


def ledger_write_is_direct(db: Session, client_id: int) -> bool:
    """An approved change request that records a transaction posts it, rather than queueing it, only if allowed."""
    return operation_mode(db, client_id, "transactions.create") == "allow"


def _operation_payload(operation: AiOperation, saved: dict[str, AiMode]) -> dict[str, Any]:
    mode = saved.get(operation.key)
    return {
        "key": operation.key,
        "section": operation.section,
        "kind": operation.kind,
        "ja": operation.ja,
        "en": operation.en,
        "risk": operation.risk,
        "approval": operation.approval,
        "by_write_mode": operation.by_write_mode,
        "tools": list(operation.tools),
        "modes": list(operation.modes),
        "mode": mode if mode in operation.modes else operation.default,
        "saved": mode in operation.modes,
    }


def list_operations(db: Session, client_id: int) -> dict[str, Any]:
    """Every operation, grouped by section, with the mode in effect (saved, or the default)."""
    saved = _saved_modes(db, client_id)
    return {
        "sections": [
            {
                "key": section.key, "ja": section.ja, "en": section.en,
                "operations": [_operation_payload(operation, saved)
                               for operation in ai_operations.OPERATIONS if operation.section == section.key],
            }
            for section in ai_operations.SECTIONS
        ],
        "local_tools": list(ai_operations.LOCAL_TOOLS),
    }


def set_operation_mode(db: Session, client_id: int, key: str, mode: str, expected: str | None) -> dict[str, Any]:
    """Save one operation's mode. `expected` is the mode the screen showed: another change since is a conflict."""
    operation = ai_operations.BY_KEY.get(key)
    if operation is None:
        raise NotFound("Unknown AI operation", ja="この操作は一覧にありません。")
    if mode not in operation.modes:
        raise Invalid("This operation cannot take that permission", ja="この操作にはその権限を選べません。")
    row = db.query(models.AiOperationPolicy).filter(
        models.AiOperationPolicy.client_id == client_id, models.AiOperationPolicy.operation == key,
    ).first()
    current = row.mode if row is not None and row.mode in operation.modes else operation.default
    if expected is not None and expected != current:
        raise Conflict("Changed elsewhere", ja="別の画面で変更されました。今の設定を読み込み直します。",
                       payload={"error": "changed_elsewhere", "mode": current})
    if row is None:
        row = models.AiOperationPolicy(client_id=client_id, operation=key, mode=mode)
        db.add(row)
    else:
        row.mode = mode
        row.updated_at = datetime.utcnow()
    db.commit()
    return _operation_payload(operation, {key: mode})


def write_ai_audit_log(
    db: Session,
    client_id: int,
    context: AiOperationContext,
    decision: AiDecision,
    result: dict[str, Any] | None = None,
    commit: bool = True,
) -> models.AiAuditLog:
    log = models.AiAuditLog(
        client_id=client_id,
        actor_client_id=client_id,
        mcp_client_id=context.mcp_client_id,
        source=context.source,
        tool_name=context.tool_name,
        resource=context.resource,
        action=context.action,
        risk=context.risk,
        decision=decision,
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


def list_audit_logs(
    db: Session, client_id: int, *, limit: int, offset: int,
) -> list[models.AiAuditLog]:
    return db.query(models.AiAuditLog).filter(
        models.AiAuditLog.client_id == client_id,
    ).order_by(models.AiAuditLog.created_at.desc(), models.AiAuditLog.id.desc()).offset(offset).limit(limit).all()


def redact_sensitive(value: Any, *, max_depth: int = 4) -> Any:
    return _redact(value, depth=0, max_depth=max_depth)


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

MAX_AUDITED_CHANGES = 200
MAX_REQUEST_BODY_CHARS = 4000
MAX_ERROR_CHARS = 1000
REFUSED_ERROR = "ai_operation_refused"

# What the AI may never do, whatever its permissions and write mode say: change
# its own permissions, act on the account, or approve. Approval is a person's
# decision (owner 2026-10-24); applying what a person approved stays open.
_MCP_REFUSALS: tuple[tuple[str | None, re.Pattern, str], ...] = (
    ("PUT", re.compile(r"^/ai/(operations(/.*)?|execution-settings)/?$"), "ai_permissions"),
    (None, re.compile(r"^/ai/mcp(/|$)"), "ai_connections"),
    ("POST", re.compile(r"^/ai/change-requests/\d+/(approve|reject)/?$"), "human_approval"),
    ("POST", re.compile(r"^/transactions/proposals/\d+/(approve|reject)/?$"), "human_approval"),
    (None, re.compile(r"^/auth(/|$)"), "account"),
)

REFUSAL_MESSAGES = {
    "ai_permissions": ("AI permissions are changed by a person in the app, not through MCP.",
                       "AI の権限（操作ごとの権限・書き込み方式）は MCP からは変更できません。アプリで変更してください。"),
    "operation_denied": ("This operation is not allowed for the AI in this client's settings.",
                         "この操作は AI 操作の権限で禁止されています。"),
    "operation_needs_approval": ("This operation needs a person's approval: create an AI change request instead.",
                                 "この操作は承認が必要です。承認リクエストを作ってください。"),
    "operation_unknown": ("This request is not one of the operations the AI may use.",
                          "この要求は AI が使える操作の一覧にありません。"),
    "ai_connections": ("AI app connections are seen and ended by a person in the app, not through MCP.",
                       "AI アプリの接続は MCP からは見られず、切断もできません。アプリで操作してください。"),
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


def mcp_refusal(db: Session, client_id: int, method: str, path: str) -> str | None:
    """Why the AI may not make this request, or None. Checked before the endpoint runs.

    In order: what the AI may never do; a request that is none of the operations it
    may use; the person's permission for the operation (deny); the write mode (in
    change-request mode a write goes through a change request); and a permission of
    "approval" for a direct write (WP36).
    """
    for refused_method, pattern, reason in _MCP_REFUSALS:
        if (refused_method is None or refused_method == method) and pattern.match(path):
            return reason
    known, operation = ai_operations.match(method, path)
    if not known:
        return "operation_unknown"
    if operation is None:
        return None
    mode = operation_mode(db, client_id, operation.key)
    if mode == "deny":
        return "operation_denied"
    if operation.kind == "read" or not operation.by_write_mode:
        return None
    client = db.get(models.Client, client_id)
    if mcp_write_mode_of(client.general_settings if client else None) == "change_request":
        return "change_request_mode"
    return "operation_needs_approval" if mode == "approval" else None


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


_POLICY_REFUSALS = frozenset({"operation_denied", "operation_needs_approval"})


def _authorize(
    db: Session, client_id: int, facts: McpRequestFacts, operation: AiOperation | None,
) -> tuple[AiAuthorization, AiDecision, dict]:
    """What let the request through or stopped it, and the facts that show it."""
    client = db.get(models.Client, client_id)
    write_mode = mcp_write_mode_of(client.general_settings if client else None)
    detail: dict[str, Any] = {"mcp_write_mode": write_mode}
    if operation is not None:
        detail["operation"] = {"key": operation.key, "mode": operation_mode(db, client_id, operation.key)}
    error = _error_payload(facts.error)
    refusal = facts.refusal or (error.get("reason") if error.get("error") == REFUSED_ERROR else None)
    if refusal:
        detail["refusal"] = refusal
        authorization: AiAuthorization = (
            "refused_mode" if refusal == "change_request_mode"
            else "refused_policy" if refusal in _POLICY_REFUSALS else "refused_scope"
        )
        return authorization, "denied", detail
    if facts.status in {401, 403}:
        return "refused_policy", "denied", detail
    if facts.status >= 400:
        return "failed", "failed", detail
    if operation is None:
        # Only rows restored from the logs of requests made before the operation list.
        return ("read", "allowed", detail) if facts.method in {"GET", "HEAD"} else ("direct_mode", "applied", detail)
    if operation.kind == "read":
        return "read", "allowed", detail
    if operation.key == "change_requests.create":
        return "change_request", "approval_required", detail
    if operation.key == "change_requests.apply":
        # Only a person can approve (the refusals above), so an applied request was approved by one.
        return "human_approved", "applied", detail
    # A direct write runs only with the operation's permission at "allow" (WP36).
    return "direct_policy", "applied", detail


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
    _, operation = ai_operations.match(facts.method, facts.path)
    if operation is not None:
        resource, action, risk = operation.resource, operation.action, operation.risk
    own_rows = [change.get("pk") for change in facts.changes
                if change.get("table") == "ai_audit_logs" and change.get("op") == "insert"]
    changes = [change for change in facts.changes if change.get("table") != "ai_audit_logs"]
    facts = replace(facts, changes=changes)
    authorization, decision, detail = _authorize(db, client_id, facts, operation)
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
        approval_request_id = target if operation is not None and operation.key == "change_requests.apply" else None
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
