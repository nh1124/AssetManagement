"""Structured logging: who did what, through which door, and what it changed.

Four layers, each one log line (or more) per unit of work:

    request.*    one HTTP request            (middleware.RequestLogMiddleware)
    op.*         one named operation         (operation.operation)
    db.change    one row written             (db_audit.install_db_audit)
    db.statement one slow or traced query    (sql_timing.install_sql_timing)

Every line carries the request context (context.RequestContext), so the rows a
request changed can be found from its request id and the reverse.
"""
from .context import RequestContext, bind, current, reset
from .db_audit import install_db_audit
from .logging_setup import log_event, setup_logging
from .middleware import RequestLogMiddleware
from .operation import operation
from .sql_timing import install_sql_timing

__all__ = [
    "RequestContext",
    "RequestLogMiddleware",
    "bind",
    "current",
    "install_db_audit",
    "install_sql_timing",
    "log_event",
    "operation",
    "reset",
    "setup_logging",
]
