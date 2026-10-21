"""The log is a record: these tests pin what it says and, above all, what it
must never say (a change that was rolled back, a secret, a request body)."""
from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.dependencies import get_current_client
from backend.app.domain.errors import NotFound
from backend.app.utils.jwt import create_access_token
from backend.app.utils.observability import (
    RequestContext,
    RequestLogMiddleware,
    bind,
    install_db_audit,
    install_sql_timing,
    operation,
    reset,
)
from backend.app.utils.observability.logging_setup import JsonFormatter, log_event


def _events(caplog, name: str) -> list[dict]:
    return [
        record.fields for record in caplog.records
        if getattr(record, "fields", {}).get("event") == name
    ]


@pytest.fixture
def audited_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    assert install_db_audit(factory)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _client(**fields) -> models.Client:
    values = {"name": "tester", "username": "tester", "password_hash": "bcrypt-hash"}
    values.update(fields)
    return models.Client(**values)


# --- formatter -------------------------------------------------------------

def test_a_json_line_carries_the_request_context_and_the_event_fields():
    token = bind(RequestContext(request_id="r1", correlation_id="c1", actor_client_id=2, channel="mcp", mcp_tool="tx"))
    try:
        record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "thing.happened", None, None)
        record.fields = {"event": "thing.happened", "amount": 1200}
        line = json.loads(JsonFormatter().format(record))
    finally:
        reset(token)
    assert line["event"] == "thing.happened"
    assert line["amount"] == 1200
    assert (line["request_id"], line["correlation_id"], line["actor_client_id"]) == ("r1", "c1", 2)
    assert (line["channel"], line["mcp_tool"]) == ("mcp", "tx")
    assert "mcp_client_id" not in line  # empty context fields are omitted


def test_outside_a_request_the_channel_is_system():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "startup", None, None)
    line = json.loads(JsonFormatter().format(record))
    assert line["channel"] == "system"
    assert "request_id" not in line


# --- request middleware ----------------------------------------------------

@pytest.fixture
def http():
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)

    @app.get("/things/{thing_id}")
    def read_thing(thing_id: int):
        return {"id": thing_id}

    @app.post("/things")
    def create_thing(payload: dict):
        return payload

    @app.get("/refused")
    def refused():
        raise HTTPException(status_code=403, detail="no")

    @app.get("/broken")
    def broken():
        raise RuntimeError("boom")

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    return TestClient(app, raise_server_exceptions=False)


def test_a_request_is_logged_at_its_start_and_at_its_end(http, caplog):
    caplog.set_level(logging.INFO, logger="app.request")
    response = http.get("/things/7?verbose=1", headers={"User-Agent": "pytest"})
    (start,) = _events(caplog, "request.start")
    (end,) = _events(caplog, "request.end")
    assert (start["method"], start["path"], start["query"]) == ("GET", "/things/7", "verbose=1")
    assert (end["status"], end["path"]) == (200, "/things/7")
    assert end["duration_ms"] >= 0
    assert end["response_bytes"] == len(response.content)


def test_the_response_names_the_request_so_a_user_report_can_be_traced(http):
    # A real handler, because the context is merged in when the line is
    # written, while the request is still in progress.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    request_logger = logging.getLogger("app.request")
    request_logger.addHandler(handler)
    previous_level = request_logger.level
    request_logger.setLevel(logging.INFO)
    try:
        response = http.get("/things/1")
    finally:
        request_logger.removeHandler(handler)
        request_logger.setLevel(previous_level)

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [line["event"] for line in lines] == ["request.start", "request.end"]
    assert {line["request_id"] for line in lines} == {request_id}
    assert {line["channel"] for line in lines} == {"ui"}


def test_an_upstream_id_becomes_the_correlation_id_only_if_it_looks_like_an_id(http):
    seen: list[RequestContext] = []
    app = http.app

    @app.get("/context")
    def context_probe():
        from backend.app.utils.observability import current
        seen.append(current())
        return {}

    http.get("/context", headers={"X-Request-ID": "abcdef0123456789"})
    http.get("/context", headers={"X-Request-ID": 'x"\n{"forged":true}'})
    http.get("/context")
    assert seen[0].correlation_id == "abcdef0123456789"
    assert seen[0].request_id != seen[0].correlation_id
    assert seen[1].correlation_id == seen[1].request_id
    assert seen[2].correlation_id == seen[2].request_id


def test_the_actor_and_the_mcp_tool_are_read_from_the_request(http):
    seen: list[RequestContext] = []

    @http.app.get("/who")
    def who():
        from backend.app.utils.observability import current
        seen.append(current())
        return {}

    token = create_access_token(user_id=2, username="owner")
    http.get("/who", headers={"Authorization": f"Bearer {token}"})
    http.get("/who", headers={
        "Authorization": f"Bearer {token}",
        "X-MCP-Client-Id": "mcp_abc",
        "X-MCP-Tool-Name": "transactions_create",
    })
    http.get("/who", headers={"Authorization": "Bearer not-a-token"})
    assert (seen[0].actor_client_id, seen[0].channel) == (2, "ui")
    assert (seen[1].channel, seen[1].mcp_client_id, seen[1].mcp_tool) == ("mcp", "mcp_abc", "transactions_create")
    assert seen[2].actor_client_id is None


def test_neither_the_body_nor_the_credential_reaches_the_log(http, caplog):
    caplog.set_level(logging.DEBUG)
    token = create_access_token(user_id=2, username="owner")
    http.post("/things", json={"password": "hunter2-secret"}, headers={"Authorization": f"Bearer {token}"})
    rendered = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    assert "hunter2-secret" not in rendered
    assert token not in rendered


def test_a_refusal_ends_normally_and_a_crash_is_an_error(http, caplog):
    caplog.set_level(logging.INFO, logger="app.request")
    assert http.get("/refused").status_code == 403
    assert _events(caplog, "request.end")[-1]["status"] == 403
    assert not _events(caplog, "request.error")

    assert http.get("/broken").status_code == 500
    (error,) = _events(caplog, "request.error")
    assert error["path"] == "/broken"
    record = next(r for r in caplog.records if getattr(r, "fields", {}).get("event") == "request.error")
    assert "RuntimeError: boom" in JsonFormatter().format(record)


def test_health_polls_do_not_fill_the_log(http, caplog):
    caplog.set_level(logging.INFO, logger="app.request")
    assert http.get("/health").status_code == 200
    assert not _events(caplog, "request.start")
    assert not _events(caplog, "request.end")


# --- operation decorator ---------------------------------------------------

def test_an_operation_is_logged_at_its_start_and_at_its_end(caplog):
    caplog.set_level(logging.INFO, logger="app.operation")

    @operation("ledger.post_entry", log_args=("client_id",))
    def post_entry(db, client_id, payload):
        return "posted"

    assert post_entry(object(), 2, {"amount": 5000}) == "posted"
    (start,) = _events(caplog, "op.start")
    (end,) = _events(caplog, "op.end")
    assert start == {"event": "op.start", "op": "ledger.post_entry", "client_id": 2}
    assert (end["op"], end["outcome"]) == ("ledger.post_entry", "ok")
    assert post_entry.__name__ == "post_entry"


def test_a_domain_refusal_is_an_outcome_and_anything_else_is_an_error(caplog):
    caplog.set_level(logging.INFO, logger="app.operation")

    @operation("goal.delete")
    def refuse():
        raise NotFound("no such goal")

    @operation("goal.delete")
    def crash():
        raise ZeroDivisionError

    with pytest.raises(NotFound):
        refuse()
    with pytest.raises(ZeroDivisionError):
        crash()
    (end,) = _events(caplog, "op.end")
    (error,) = _events(caplog, "op.error")
    assert (end["outcome"], end["error_type"]) == ("refused", "NotFound")
    assert error["error_type"] == "ZeroDivisionError"


def test_an_async_operation_is_timed_across_its_await(caplog):
    caplog.set_level(logging.INFO, logger="app.operation")

    @operation("ai.analyze")
    async def analyze():
        await asyncio.sleep(0.01)
        return 1

    assert asyncio.run(analyze()) == 1
    (end,) = _events(caplog, "op.end")
    assert end["duration_ms"] >= 10


# --- database audit --------------------------------------------------------

def test_an_insert_is_recorded_with_its_generated_key_when_it_commits(audited_db, caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    client = _client()
    audited_db.add(client)
    audited_db.flush()
    assert not _events(caplog, "db.change"), "nothing is reported before the commit"
    audited_db.commit()
    (change,) = _events(caplog, "db.change")
    assert (change["table"], change["op"], change["pk"]) == ("clients", "insert", client.id)
    assert change["values"]["username"] == "tester"
    (commit,) = _events(caplog, "db.commit")
    assert commit["changes"] == 1 and commit["tables"] == {"clients": 1}


def test_an_update_records_the_old_and_the_new_value_of_what_changed(audited_db, caplog):
    client = _client()
    audited_db.add(client)
    audited_db.commit()
    caplog.set_level(logging.INFO, logger="app.audit")
    caplog.clear()

    client.name = "renamed"
    audited_db.commit()
    (change,) = _events(caplog, "db.change")
    assert (change["op"], change["pk"]) == ("update", client.id)
    assert change["changes"] == {"name": ["tester", "renamed"]}


def test_a_delete_records_the_row_that_is_gone(audited_db, caplog):
    client = _client()
    audited_db.add(client)
    audited_db.commit()
    client_id = client.id
    caplog.set_level(logging.INFO, logger="app.audit")
    caplog.clear()

    audited_db.delete(client)
    audited_db.commit()
    (change,) = _events(caplog, "db.change")
    assert (change["op"], change["pk"]) == ("delete", client_id)
    assert change["values"]["username"] == "tester"


def test_a_rolled_back_change_is_never_reported_as_made(audited_db, caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    audited_db.add(_client())
    audited_db.flush()
    audited_db.rollback()
    assert not _events(caplog, "db.change")
    assert _events(caplog, "db.rollback") == [{"event": "db.rollback", "discarded_changes": 1}]

    # The discarded change must not ride along on the next commit either.
    audited_db.add(_client(name="second", username="second"))
    audited_db.commit()
    (change,) = _events(caplog, "db.change")
    assert change["values"]["username"] == "second"


def test_a_session_closed_mid_transaction_reports_nothing_later(audited_db, caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    audited_db.add(_client())
    audited_db.flush()
    audited_db.close()
    audited_db.add(_client(name="after", username="after"))
    audited_db.commit()
    changes = _events(caplog, "db.change")
    assert [change["values"]["username"] for change in changes] == ["after"]


def test_secrets_are_redacted_by_column_name(audited_db, caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    client = _client(password_hash="$2b$12$real-hash")
    audited_db.add(client)
    audited_db.commit()
    client.password_hash = "$2b$12$new-hash"
    audited_db.add(models.ClientMfaSetting(client_id=client.id, totp_secret_encrypted="gAAAA-totp"))
    audited_db.add(models.ClientRecoveryCode(client_id=client.id, code_hash="$2b$12$code"))
    audited_db.commit()

    rendered = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    for secret in ("real-hash", "new-hash", "gAAAA-totp", "$2b$12$code"):
        assert secret not in rendered
    update = next(c for c in _events(caplog, "db.change") if c["op"] == "update")
    assert update["changes"]["password_hash"] == ["[redacted]", "[redacted]"]


def test_a_bulk_statement_is_recorded_with_its_row_count(audited_db, caplog):
    for index in range(3):
        audited_db.add(_client(name=f"c{index}", username=f"c{index}"))
    audited_db.commit()
    caplog.set_level(logging.INFO, logger="app.audit")
    caplog.clear()

    deleted = audited_db.query(models.Client).filter(models.Client.username != "c0").delete(synchronize_session=False)
    updated = audited_db.query(models.Client).update({"name": "kept"}, synchronize_session=False)
    audited_db.commit()
    assert (deleted, updated) == (2, 1)
    assert [(c["table"], c["op"], c["rows"]) for c in _events(caplog, "db.change")] == [
        ("clients", "bulk_delete", 2),
        ("clients", "bulk_update", 1),
    ]
    assert audited_db.query(models.Client).one().name == "kept"


def test_a_long_value_is_truncated_rather_than_dropped(audited_db, caplog):
    caplog.set_level(logging.INFO, logger="app.audit")
    audited_db.add(_client(general_settings={"note": "x" * 5000}))
    audited_db.commit()
    (change,) = _events(caplog, "db.change")
    assert len(change["values"]["general_settings"]) < 1100
    assert change["values"]["general_settings"].endswith("…")


def test_installing_twice_does_not_record_each_change_twice(audited_db, caplog):
    factory = sessionmaker(bind=audited_db.get_bind(), autoflush=False)
    assert install_db_audit(factory) and install_db_audit(factory)
    caplog.set_level(logging.INFO, logger="app.audit")
    session = factory()
    session.add(_client())
    session.commit()
    session.close()
    assert len(_events(caplog, "db.change")) == 1


def test_the_audit_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("LOG_DB_CHANGES", "0")
    assert install_db_audit(sessionmaker()) is False


# --- sql timing ------------------------------------------------------------

def test_only_slow_statements_are_logged_and_never_their_parameters(monkeypatch, caplog):
    monkeypatch.setenv("LOG_SLOW_SQL_MS", "0")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    install_sql_timing(engine)
    caplog.set_level(logging.WARNING, logger="app.sql")
    session = sessionmaker(bind=engine)()
    session.add(_client(username="param-value-xyz"))
    session.commit()
    session.close()
    statements = _events(caplog, "db.statement")
    assert any(s["statement"].startswith("INSERT INTO clients") for s in statements)
    assert all(s["slow"] for s in statements)
    assert "param-value-xyz" not in json.dumps(statements)

    quiet = create_engine("sqlite:///:memory:")
    monkeypatch.setenv("LOG_SLOW_SQL_MS", "60000")
    install_sql_timing(quiet)
    caplog.clear()
    with quiet.connect() as connection:
        connection.exec_driver_sql("select 1")
    assert not _events(caplog, "db.statement")


# --- authentication boundary ----------------------------------------------

def test_a_deactivated_client_cannot_use_a_token_issued_before(audited_db):
    from fastapi.security import HTTPAuthorizationCredentials

    client = _client()
    audited_db.add(client)
    audited_db.commit()
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=create_access_token(user_id=client.id, username="tester"),
    )
    assert asyncio.run(get_current_client(credentials, audited_db)) is client

    client.is_active = False
    audited_db.commit()
    with pytest.raises(HTTPException) as refused:
        asyncio.run(get_current_client(credentials, audited_db))
    assert refused.value.status_code == 401
