"""The identity of the work in progress, carried without being passed.

A context variable rather than an argument: the layers that write log lines
(the session's flush hook, a service three calls deep) have no request object,
and threading one through 282 session-taking functions is not on offer.
Starlette copies the context into the worker thread that runs a sync endpoint,
so the value set by the middleware is the value the flush hook reads.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RequestContext:
    # Unique to one backend request.
    request_id: str = ""
    # Shared by everything one outside action caused: the id nginx assigned,
    # or the id an MCP tool call sent with each of its backend requests.
    correlation_id: str = ""
    actor_client_id: int | None = None
    # ui | mcp | system. "system" is work no request started (startup, the
    # recurring auto-post loop).
    channel: str = "system"
    mcp_client_id: str | None = None
    mcp_tool: str | None = None


_current: ContextVar[RequestContext] = ContextVar("am_request_context", default=RequestContext())


def current() -> RequestContext:
    return _current.get()


def bind(context: RequestContext) -> Token:
    return _current.set(context)


def reset(token: Token) -> None:
    _current.reset(token)


def fields() -> dict:
    """The context as log fields, without the ones that carry nothing."""
    return {key: value for key, value in asdict(current()).items() if value not in ("", None)}
