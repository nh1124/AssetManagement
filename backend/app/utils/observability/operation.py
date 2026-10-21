"""Log the start and the end of one named operation.

    @operation("ledger.post_entry")
    def post_entry(db, client_id, payload): ...

writes `op.start`, then `op.end` with the duration, or `op.error` with the
exception type. Arguments are not logged unless named in `log_args`, because
most of them are sessions, ORM rows and payloads that db_audit already
records as the rows they turn into.

A DomainError is an answer ("that account does not exist"), not a fault, so it
ends the operation at INFO with `outcome=refused`; anything else is an ERROR.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time

from ...domain.errors import DomainError
from .logging_setup import log_event

logger = logging.getLogger("app.operation")


def operation(name: str, *, log_args: tuple[str, ...] = ()):
    def decorate(function):
        signature = inspect.signature(function)

        def picked(args, kwargs) -> dict:
            if not log_args:
                return {}
            bound = signature.bind_partial(*args, **kwargs).arguments
            return {key: bound[key] for key in log_args if key in bound}

        def finish(started: float, error: BaseException | None) -> None:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            if error is None:
                log_event(logger, "op.end", op=name, outcome="ok", duration_ms=duration_ms)
            elif isinstance(error, DomainError):
                log_event(
                    logger, "op.end", op=name, outcome="refused",
                    error_type=type(error).__name__, duration_ms=duration_ms,
                )
            else:
                log_event(
                    logger, "op.error", logging.ERROR, op=name,
                    error_type=type(error).__name__, duration_ms=duration_ms,
                )

        if asyncio.iscoroutinefunction(function):
            @functools.wraps(function)
            async def async_wrapper(*args, **kwargs):
                log_event(logger, "op.start", op=name, **picked(args, kwargs))
                started = time.perf_counter()
                try:
                    result = await function(*args, **kwargs)
                except BaseException as error:
                    finish(started, error)
                    raise
                finish(started, None)
                return result

            return async_wrapper

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            log_event(logger, "op.start", op=name, **picked(args, kwargs))
            started = time.perf_counter()
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                finish(started, error)
                raise
            finish(started, None)
            return result

        return wrapper

    return decorate
