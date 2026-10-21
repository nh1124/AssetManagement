"""One JSON object per line on stdout.

stdout because the container runtime already collects it; JSON because the
lines are meant to be filtered by request id, actor and table afterwards.
LOG_FORMAT=text keeps a readable format for a terminal.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

from . import context

_OWNED = "_am_observability_handler"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(context.fields())
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            line += " " + " ".join(f"{key}={value}" for key, value in fields.items() if key != "event")
        return line


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, *, exc_info=None, **fields) -> None:
    """Log a named event with structured fields.

    The event name is also the message, so a text-format log stays readable.
    """
    if logger.isEnabledFor(level):
        logger.log(level, event, exc_info=exc_info, extra={"fields": {"event": event, **fields}})


def setup_logging() -> None:
    """Route every logger through one stdout handler. Safe to call again.

    Called a second time after Alembic runs: its fileConfig() replaces the root
    handlers with the ones in alembic.ini, which would drop the JSON handler.
    """
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    as_json = os.getenv("LOG_FORMAT", "json").strip().lower() != "text"

    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _OWNED, True)
    handler.setFormatter(
        JsonFormatter() if as_json
        else TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    # Drop our previous handler and bare console handlers (Alembic's). The
    # exact-type test keeps subclasses such as pytest's capture handler.
    root.handlers = [
        existing for existing in root.handlers
        if not getattr(existing, _OWNED, False) and type(existing) is not logging.StreamHandler
    ]
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # request.end carries what the access log line would, plus the duration.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
