"""Time every SQL statement; log the slow ones, or all of them on request.

    LOG_SLOW_SQL_MS=500   statements at or above this are logged at WARNING
    LOG_SQL=1             every statement is logged at DEBUG (needs LOG_LEVEL=DEBUG)

Parameters are never logged: they are the data, and db_audit already records
what was written.
"""
from __future__ import annotations

import logging
import os
import time
import weakref

from sqlalchemy import event

from .logging_setup import log_event

logger = logging.getLogger("app.sql")

_STARTED = "am_sql_started"
# Weak, so a disposed engine's entry goes with it; an id() would be reused by
# the next engine and silently skip it.
_INSTALLED: weakref.WeakSet = weakref.WeakSet()
_MAX_STATEMENT = 500


def install_sql_timing(engine) -> None:
    if engine in _INSTALLED:
        return
    slow_ms = float(os.getenv("LOG_SLOW_SQL_MS", "500"))
    trace_all = os.getenv("LOG_SQL", "0").strip() in {"1", "true", "yes"}

    @event.listens_for(engine, "before_cursor_execute")
    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault(_STARTED, []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started = conn.info.get(_STARTED)
        if not started:
            return
        duration_ms = round((time.perf_counter() - started.pop()) * 1000, 1)
        slow = duration_ms >= slow_ms
        if slow or trace_all:
            log_event(
                logger, "db.statement", logging.WARNING if slow else logging.DEBUG,
                duration_ms=duration_ms,
                slow=slow,
                rows=cursor.rowcount,
                statement=" ".join(statement.split())[:_MAX_STATEMENT],
            )

    _INSTALLED.add(engine)
