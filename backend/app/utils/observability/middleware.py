"""Log the start and the end of every HTTP request.

A plain ASGI middleware rather than BaseHTTPMiddleware: the latter runs the
endpoint in a different task, and the context set here would not be the one
the endpoint sees.

Bodies are never logged. What a request changed is recorded by db_audit, row
by row, with the same request id.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from ..jwt import decode_token
from .context import RequestContext, bind, reset
from .logging_setup import log_event

logger = logging.getLogger("app.request")

# An id from outside is echoed into logs, so it is accepted only in a shape
# that cannot carry anything but an id.
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
# Polled every few seconds by the container health checks.
QUIET_PATHS = frozenset({"/health", "/health/ready"})


def _token_identity(authorization: str | None) -> tuple[int | None, str | None]:
    """Who the bearer token is for, and the MCP client it was exchanged for, if any.

    A token from /auth/mcp/exchange carries chn=mcp (WP34): the channel comes
    from the token, so an MCP request cannot pass as a screen's by leaving out
    a header.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None, None
    payload = decode_token(authorization[7:].strip())
    if not payload or payload.get("type") != "access":
        return None, None
    try:
        actor = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None, None
    if payload.get("chn") != "mcp":
        return actor, None
    return actor, str(payload.get("mcp_client_id") or "") or "mcp"


class RequestLogMiddleware:
    def __init__(self, app, component="backend"):
        self.app = app
        self.component = component

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = uuid.uuid4().hex
        incoming_id = headers.get("x-request-id", "")
        actor_client_id, token_mcp_client = (
            (None, None) if self.component == "admin" else _token_identity(headers.get("authorization"))
        )
        # The token decides when it can; the header still marks requests made with
        # tokens issued before the claim existed.
        mcp_client_id = token_mcp_client or headers.get("x-mcp-client-id") or None
        token = bind(RequestContext(
            request_id=request_id,
            correlation_id=incoming_id if _SAFE_ID.fullmatch(incoming_id) else request_id,
            actor_client_id=actor_client_id,
            channel="mcp" if mcp_client_id else "ui",
            mcp_client_id=mcp_client_id,
            mcp_tool=headers.get("x-mcp-tool-name") or None,
        ))

        path = scope.get("path", "")
        level = logging.DEBUG if path in QUIET_PATHS else logging.INFO
        client = scope.get("client") or ("", 0)
        request_fields = {
            "component": self.component,
            "method": scope.get("method", ""),
            "path": path,
        }
        started = time.perf_counter()
        status = 500
        response_bytes = 0

        async def send_with_request_id(message):
            nonlocal status, response_bytes
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [*message.get("headers", []), (b"x-request-id", request_id.encode())],
                }
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        log_event(
            logger, "request.start", level,
            **request_fields,
            query=scope.get("query_string", b"").decode("latin-1")[:500],
            client_ip=client[0],
            # Recorded as claimed: only the proxy in front can vouch for these.
            forwarded_for=headers.get("cf-connecting-ip") or headers.get("x-forwarded-for") or "",
            user_agent=headers.get("user-agent", "")[:200],
        )
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            log_event(
                logger, "request.error", logging.ERROR, exc_info=True,
                **request_fields,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            raise
        else:
            log_event(
                logger, "request.end", logging.WARNING if status >= 500 else level,
                **request_fields,
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                response_bytes=response_bytes,
            )
        finally:
            reset(token)
