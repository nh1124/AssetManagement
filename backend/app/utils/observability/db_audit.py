"""Record every row the application writes, as it commits.

Hooked on the session, not on the services, so it cannot be forgotten: a new
service that writes a table is audited without knowing this module exists.

A change is buffered when it is flushed and written only when the transaction
commits. A rollback discards the buffer, so the log never reports a change
that did not happen.

Two write paths exist and both are covered:

    unit of work   db.add(row), row.x = 1, db.delete(row)   -> before/after_flush
    bulk           query.update(...), query.delete(...)     -> do_orm_execute

A bulk statement bypasses the unit of work, so there are no row images to
record; the line carries the table and the number of rows it touched.
"""
from __future__ import annotations

import json
import logging
import os
import re
import weakref
from contextvars import ContextVar, Token
from datetime import date, datetime

from sqlalchemy import event, inspect, select

from .logging_setup import log_event

logger = logging.getLogger("app.audit")

_BUFFER = "am_audit_buffer"
_PENDING = "am_audit_pending"

# The committed changes of the request in progress, for whoever asked to see
# them (the AI operation audit, WP34). A list, not a value: the endpoint runs in
# a worker thread with a copy of the context, and appends to the same list.
_collected: ContextVar[list | None] = ContextVar("am_audit_collected", default=None)

# Targets already hooked. Not event.contains(): SQLAlchemy keys that registry by
# id(target), so a new sessionmaker allocated where a dead one lived looked
# hooked and went unaudited (seen in the tests, which make one per test).
_INSTALLED: "weakref.WeakSet" = weakref.WeakSet()


def start_collecting() -> tuple[Token, list]:
    changes: list = []
    return _collected.set(changes), changes


def stop_collecting(token: Token) -> None:
    _collected.reset(token)

# Columns whose values must not reach a log, by name.
_REDACTED = re.compile(r"password|secret|token|api_key|code_hash|ai_config", re.IGNORECASE)
_MAX_TEXT = 300
_MAX_JSON = 1000


def _safe(column: str, value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if _REDACTED.search(column):
        return "[redacted]"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
        return text if len(text) <= _MAX_JSON else text[:_MAX_JSON] + "…"
    text = str(value)
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "…"


def _identity(obj):
    # Read from the instance, not from the identity map: at after_flush a new
    # row has its generated key but has not been given an identity yet.
    key = inspect(obj).mapper.primary_key_from_instance(obj)
    return key[0] if len(key) == 1 else list(key)


def _loaded_values(obj) -> dict:
    state = inspect(obj)
    return {
        attr.key: _safe(attr.key, state.dict[attr.key])
        for attr in state.mapper.column_attrs
        if attr.key in state.dict
    }


def _changed_values(session, obj) -> dict:
    state = inspect(obj)
    changed = {}
    unknown_old = []
    for attr in state.mapper.column_attrs:
        history = state.attrs[attr.key].history
        if not history.has_changes():
            continue
        new = history.added[0] if history.added else None
        if history.deleted:
            changed[attr.key] = [history.deleted[0], new]
        else:
            # Assigned without being read first (typically a row expired by
            # the previous commit): the session never held the old value.
            changed[attr.key] = [None, new]
            unknown_old.append(attr)

    if unknown_old and state.identity is not None:
        # One read of the stored row, on the flush's own connection, so the
        # "before" side of the record is the truth rather than a guess.
        mapper = state.mapper
        statement = select(*(attr.columns[0] for attr in unknown_old))
        for column, value in zip(mapper.primary_key, state.identity):
            statement = statement.where(column == value)
        row = session.connection().execute(statement).one_or_none()
        if row is not None:
            for attr, old in zip(unknown_old, row):
                changed[attr.key][0] = old

    return {
        key: [_safe(key, old), _safe(key, new)]
        for key, (old, new) in changed.items()
        # Re-assigning the stored value is not a change.
        if old != new
    }


def _before_flush(session, flush_context, instances) -> None:
    pending = session.info.setdefault(_PENDING, [])
    for obj in session.new:
        pending.append(("insert", obj, None))
    for obj in session.dirty:
        if session.is_modified(obj):
            changes = _changed_values(session, obj)
            if changes:
                pending.append(("update", obj, changes))
    for obj in session.deleted:
        pending.append(("delete", obj, _loaded_values(obj)))


def _after_flush(session, flush_context) -> None:
    buffer = session.info.setdefault(_BUFFER, [])
    for op, obj, detail in session.info.pop(_PENDING, []):
        record = {"table": obj.__table__.name, "op": op, "pk": _identity(obj)}
        if op == "insert":
            # Read after the flush so generated keys and defaults are present.
            record["values"] = _loaded_values(obj)
        elif op == "update":
            record["changes"] = detail
        else:
            record["values"] = detail
        buffer.append(record)


def _do_orm_execute(orm_execute_state):
    if not (orm_execute_state.is_update or orm_execute_state.is_delete):
        return None
    result = orm_execute_state.invoke_statement()
    table = getattr(getattr(orm_execute_state.statement, "table", None), "name", "unknown")
    orm_execute_state.session.info.setdefault(_BUFFER, []).append({
        "table": table,
        "op": "bulk_update" if orm_execute_state.is_update else "bulk_delete",
        "rows": result.rowcount,
    })
    return result


def _after_commit(session) -> None:
    buffer = session.info.pop(_BUFFER, [])
    session.info.pop(_PENDING, None)
    if not buffer:
        return
    collected = _collected.get()
    if collected is not None:
        collected.extend(buffer)
    for sequence, record in enumerate(buffer, start=1):
        log_event(logger, "db.change", seq=sequence, **record)
    tables: dict[str, int] = {}
    for record in buffer:
        tables[record["table"]] = tables.get(record["table"], 0) + 1
    log_event(logger, "db.commit", changes=len(buffer), tables=tables)


def _after_rollback(session) -> None:
    discarded = len(session.info.pop(_BUFFER, []))
    session.info.pop(_PENDING, None)
    if discarded:
        log_event(logger, "db.rollback", discarded_changes=discarded)


def _after_transaction_end(session, transaction) -> None:
    # A session closed without commit or rollback ends its transaction
    # silently. Whatever is still buffered then was never committed, and must
    # not surface on a later commit of the same session object.
    if transaction.parent is None:
        _after_rollback(session)


def install_db_audit(target) -> bool:
    """Audit sessions made by `target` (a sessionmaker, or the Session class).

    Returns False when LOG_DB_CHANGES=0 turned the audit off.
    """
    if os.getenv("LOG_DB_CHANGES", "1").strip() in {"0", "false", "no"}:
        return False
    if target in _INSTALLED:
        return True
    event.listen(target, "before_flush", _before_flush)
    event.listen(target, "after_flush", _after_flush)
    event.listen(target, "do_orm_execute", _do_orm_execute)
    event.listen(target, "after_commit", _after_commit)
    event.listen(target, "after_rollback", _after_rollback)
    event.listen(target, "after_transaction_end", _after_transaction_end)
    _INSTALLED.add(target)
    return True
