from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.services import ai_change_request_store as store


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add_all([
        models.Client(id=1, name="request-owner", general_settings={}),
        models.Client(id=2, name="other-client", general_settings={}),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _fields(key, **overrides):
    return {
        "source": "backend",
        "resource": "transactions",
        "action": "create",
        "risk": "medium",
        "status": "pending",
        "idempotency_key": key,
        "input_payload": {"amount": 500},
        "diff": {"count": 1},
        "precondition_hash": "already-computed",
        **overrides,
    }


def test_find_by_idempotency_key_never_satisfies_another_clients_request(db):
    other = store.create(db, 2, _fields("same-key"), commit=True)
    assert store.find_by_idempotency_key(db, 1, "same-key") is None
    own = store.create(db, 1, _fields("same-key"), commit=True)
    assert store.find_by_idempotency_key(db, 1, "same-key") is own
    assert store.find_by_idempotency_key(db, 2, "same-key") is other
    assert store.find_by_idempotency_key(db, 1, "unknown-key") is None


def test_create_assigns_an_id_without_committing_the_callers_transaction(db):
    fields = _fields("rollbackable")
    row = store.create(db, 1, fields)
    row_id = row.id
    assert row_id is not None
    assert db.query(models.AiChangeRequest).all() == [row]
    assert row.client_id == 1
    assert all(getattr(row, name) == value for name, value in fields.items())
    db.rollback()
    assert store.get(db, 1, row_id) is None
    assert db.query(models.AiChangeRequest).count() == 0

    committed = store.create(db, 1, _fields("committed"), commit=True)
    committed_id = committed.id
    db.rollback()
    assert store.get(db, 1, committed_id) is committed
    assert db.query(models.AiChangeRequest).count() == 1


def test_get_returns_none_for_unknown_and_other_client_ids(db):
    row = store.create(db, 2, _fields("other"), commit=True)
    assert store.get(db, 1, 999999) is None
    assert store.get(db, 1, row.id) is None
    assert store.get(db, 2, row.id) is row
    assert store.get(db, 1, row.id, for_update=True) is None


def test_get_for_update_preserves_the_row_and_postgresql_lock_on_sqlite(db):
    row = store.create(db, 1, _fields("locked"), commit=True)
    statements = []

    def capture(orm_execute_state):
        statements.append(orm_execute_state.statement)

    event.listen(db, "do_orm_execute", capture)
    try:
        assert store.get(db, 1, row.id) is row
        assert store.get(db, 1, row.id, for_update=True) is row
    finally:
        event.remove(db, "do_orm_execute", capture)

    # SQLite omits row locks; compile the executed query for production's
    # dialect so losing FOR UPDATE cannot pass through that omission unnoticed.
    plain_sql, locked_sql = [str(statement.compile(dialect=postgresql.dialect())) for statement in statements]
    assert "FOR UPDATE" not in plain_sql
    assert locked_sql.endswith("FOR UPDATE")
    assert str(statements[1].compile(dialect=db.get_bind().dialect)) == str(
        statements[0].compile(dialect=db.get_bind().dialect)
    )


def test_list_for_client_preserves_status_order_and_endpoint_pagination(db):
    older = datetime(2026, 10, 10)
    newer = datetime(2026, 10, 11)
    first = store.create(db, 1, _fields("first", created_at=older))
    second = store.create(db, 1, _fields("second", created_at=newer))
    approved = store.create(db, 1, _fields("approved", created_at=newer, status="approved"))
    last = store.create(db, 1, _fields("last", created_at=newer))
    store.create(db, 2, _fields("other", created_at=datetime(2026, 10, 12)))
    db.commit()

    assert store.list_for_client(db, 1) == [last, approved, second, first]
    assert store.list_for_client(db, 1, status="") == [last, approved, second, first]
    assert store.list_for_client(db, 1, limit=2, offset=1) == [approved, second]
    assert store.list_for_client(db, 1, status="pending") == [last, second, first]
    assert store.list_for_client(db, 1, status="pending", limit=1, offset=1) == [second]
    assert store.list_for_client(db, 1, status="approved") == [approved]
    assert store.list_for_client(db, 1, status="rejected") == []
    assert store.list_for_client(db, 1, offset=4) == []
