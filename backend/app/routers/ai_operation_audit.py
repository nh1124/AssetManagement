"""The backend side of the MCP gateway: scope and audit every AI request (WP34).

Sits inside RequestLogMiddleware, which has bound the request context from the
bearer token (chn=mcp). For each request on the MCP channel it

1. refuses, before an endpoint runs (ai_policy_service.mcp_refusal), what the AI
   may never do -- change its own permissions, act on the account, approve --
   and any request that is none of the operations in domain/ai_operations; then
   applies the person's permission for the operation (deny, or approval for a
   direct write) and, in change-request mode, refuses direct writes (WP36);
2. lets everything else through, collecting the rows the request committed; and
3. writes one ai_audit_logs row saying what the AI did and what let it through
   or stopped it (ai_policy_service.record_mcp_operation).

A person's requests pass untouched. The audit row is written after the response
has gone out, and a failure to write it is logged for the administrator rather
than turned into a failed request.
"""
from __future__ import annotations

import json
import logging
import time

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from ..database import get_db
from ..dependencies import request_language
from ..domain.errors import detail_for, status_for
from ..services import ai_policy_service
from ..services.ai_policy_service import McpRequestFacts
from ..utils import observability

logger = logging.getLogger("app.ai_audit")

_BODY_LIMIT = 64 * 1024
_ERROR_LIMIT = 4 * 1024


def _with_session(scope, work):
    # The same session the endpoints get, so a test's database override applies here too.
    provider = getattr(scope.get("app"), "dependency_overrides", {}).get(get_db, get_db)
    sessions = provider()
    try:
        return work(next(sessions))
    finally:
        sessions.close()


async def _refuse(scope, send, reason: str) -> None:
    error = ai_policy_service.mcp_refusal_error(reason)
    payload = json.dumps(
        {"detail": detail_for(error, request_language(Request(scope)))}, ensure_ascii=False,
    ).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status_for(error),
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
    })
    await send({"type": "http.response.body", "body": payload})


class AiOperationAuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        context = observability.current()
        method, path = scope.get("method", ""), scope.get("path", "")
        client_id = context.actor_client_id
        if (
            context.channel != "mcp" or client_id is None
            or not ai_policy_service.mcp_request_is_operation(method, path)
        ):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        refusal = await run_in_threadpool(
            _with_session, scope, lambda db: ai_policy_service.mcp_refusal(db, client_id, method, path),
        )
        body = bytearray()
        error = bytearray()
        status = 500

        async def receive_and_keep():
            message = await receive()
            if message["type"] == "http.request" and len(body) < _BODY_LIMIT:
                body.extend(message.get("body", b"")[: _BODY_LIMIT - len(body)])
            return message

        async def send_and_watch(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and status >= 400 and len(error) < _ERROR_LIMIT:
                error.extend(message.get("body", b"")[: _ERROR_LIMIT - len(error)])
            await send(message)

        collecting, changes = observability.start_collecting()
        try:
            if refusal:
                # Read what was sent anyway: the audit row shows what the AI tried.
                while (await receive_and_keep()).get("more_body"):
                    pass
                await _refuse(scope, send_and_watch, refusal)
            else:
                await self.app(scope, receive_and_keep, send_and_watch)
        finally:
            observability.stop_collecting(collecting)
            headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
            facts = McpRequestFacts(
                method=method,
                path=path,
                status=status,
                query=scope.get("query_string", b"").decode("latin-1"),
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                request_id=context.request_id,
                correlation_id=context.correlation_id,
                mcp_client_id=context.mcp_client_id,
                tool_name=context.mcp_tool,
                ip_address=(scope.get("client") or ("",))[0] or None,
                user_agent=headers.get("user-agent"),
                request_body=bytes(body) if method not in {"GET", "HEAD"} else None,
                error=bytes(error) or None,
                refusal=refusal,
                changes=list(changes),
            )
            try:
                await run_in_threadpool(
                    _with_session, scope, lambda db: ai_policy_service.record_mcp_operation(db, client_id, facts),
                )
            except Exception:
                observability.log_event(
                    logger, "ai_audit.write_failed", logging.ERROR, exc_info=True, method=method, path=path,
                )
