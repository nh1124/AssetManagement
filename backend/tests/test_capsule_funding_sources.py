"""F1a stores intent without changing journal balances or rule routing."""
import asyncio
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.database import Base
from app.domain.errors import DomainError, Invalid, NotFound
from app.main import domain_error_handler
from app.routers import capsules as router
from app.services import capsule_service as service

LIVE_TARGETS = [1500000, 300000, 200000, 3500000, 6000000, 1000000,
                12000000, 2500000, 30000000, 3000000, 405050, 53239]


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add_all([
            models.Client(id=1, name="Funding", general_settings={"currency": "JPY"}),
            models.Client(id=2, name="Foreign", general_settings={"currency": "USD"}),
        ])
        session.flush()
        session.add_all([
            models.Account(id=1, client_id=1, name="Reserve", account_type="asset"),
            models.Account(id=2, client_id=1, name="Investments", account_type="asset"),
            models.Account(id=3, client_id=2, name="Foreign reserve", account_type="asset"),
        ])
        session.flush()
        session.add_all([
            models.Capsule(id=1, client_id=1, name="Savings", account_id=1,
                           target_amount_minor=1000, monthly_contribution_minor=10, current_balance_minor=0),
            models.Capsule(id=2, client_id=2, name="Foreign savings", account_id=3,
                           target_amount_minor=10000, monthly_contribution_minor=0, current_balance_minor=0),
        ])
        session.commit()
        yield session
    engine.dispose()


def _input(account_id=1, target_amount=100, sort_order=0):
    return schemas.CapsuleFundingSourceInput(
        account_id=account_id, target_amount=target_amount, sort_order=sort_order,
    )


def _plan(db, client_id=1, capsule_id=1):
    return [(row.account_id, row.target_amount_minor, row.sort_order)
            for row in service.list_funding_sources(db, client_id, capsule_id)]


def test_replaces_plan_including_retained_accounts_and_empty_plan(db):
    service.set_funding_sources(db, 1, 1, [_input(1, 400, 2), _input(2, 600, 1)])
    assert _plan(db) == [(2, 600, 1), (1, 400, 2)]
    service.set_funding_sources(db, 1, 1, [_input(1, 800, 3)])
    assert _plan(db) == [(1, 800, 3)]
    assert db.query(models.CapsuleFundingSource).count() == 1
    assert service.set_funding_sources(db, 1, 1, []) == []
    assert db.query(models.CapsuleFundingSource).count() == 0


@pytest.mark.parametrize("account_id", [3, 99999])
def test_foreign_or_absent_account_rejected_before_any_mutation(db, account_id):
    service.set_funding_sources(db, 1, 1, [_input()])
    with pytest.raises(NotFound, match="Account not found"):
        service.set_funding_sources(db, 1, 1, [_input(2), _input(account_id)])
    assert not db.new and not db.dirty and not db.deleted
    assert _plan(db) == [(1, 100, 0)]
    db.commit()
    assert _plan(db) == [(1, 100, 0)]


def test_duplicate_account_rejected_before_any_mutation(db):
    service.set_funding_sources(db, 1, 1, [_input()])
    with pytest.raises(Invalid, match="Duplicate"):
        service.set_funding_sources(db, 1, 1, [_input(2), _input(2)])
    assert not db.new and not db.dirty and not db.deleted
    assert _plan(db) == [(1, 100, 0)]


@pytest.mark.parametrize("capsule_id", [2, 99999])
def test_capsule_scope_is_checked_for_reads_and_writes(db, capsule_id):
    assert service.list_funding_sources(db, 1, capsule_id) is None
    with pytest.raises(NotFound, match="Capsule not found"):
        service.set_funding_sources(db, 1, capsule_id, [_input()])
    assert db.query(models.CapsuleFundingSource).count() == 0


def test_database_unique_constraint(db):
    service.set_funding_sources(db, 1, 1, [_input()])
    db.add(models.CapsuleFundingSource(client_id=1, capsule_id=1, account_id=1, target_amount_minor=1))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert _plan(db) == [(1, 100, 0)]


@pytest.mark.parametrize("client_id,capsule_id,account_id,major,minor", [
    (1, 1, 1, 405050, 405050), (2, 2, 3, 12.34, 1234),
])
def test_read_only_major_hybrid_in_python_sql_and_alias(db, client_id, capsule_id, account_id, major, minor):
    source = service.set_funding_sources(db, client_id, capsule_id, [_input(account_id, major)])[0]
    assert source.target_amount_minor == minor
    assert source.target_amount == major
    assert db.query(models.CapsuleFundingSource.target_amount).filter_by(id=source.id).scalar() == major
    alias = aliased(models.CapsuleFundingSource)
    assert db.query(alias.target_amount).filter(alias.id == source.id).scalar() == major
    with pytest.raises(AttributeError):
        source.target_amount = 999


def test_delete_capsule_deletes_plan_and_keeps_accounts(db):
    service.set_funding_sources(db, 1, 1, [_input(1), _input(2)])
    deleted = service.delete_capsule(db, 1, 1)
    assert deleted.retained_account_id == 1
    assert db.query(models.CapsuleFundingSource).count() == 0
    assert db.get(models.Account, 1) is not None
    assert db.get(models.Account, 2) is not None


def test_database_cascade_also_deletes_plan(db):
    service.set_funding_sources(db, 1, 1, [_input()])
    db.execute(sa.delete(models.Capsule).where(models.Capsule.id == 1))
    db.commit()
    assert db.query(models.CapsuleFundingSource).count() == 0
    assert db.get(models.Account, 1) is not None


def test_commit_false_replacement_rolls_back_all_changes(db, monkeypatch):
    service.set_funding_sources(db, 1, 1, [_input(1), _input(2, 200)])

    def unexpected(*_args, **_kwargs):
        pytest.fail("commit=False leaves commit and cache invalidation to the caller")

    monkeypatch.setattr(db, "commit", unexpected)
    monkeypatch.setattr(service, "invalidate_client", unexpected)
    service.set_funding_sources(db, 1, 1, [_input(1, 50)], commit=False)
    assert _plan(db) == [(1, 50, 0)]
    db.rollback()
    assert _plan(db) == [(1, 100, 0), (2, 200, 0)]
    service.set_funding_sources(db, 1, 1, [_input(2, 300)], commit=False)
    assert _plan(db) == [(2, 300, 0)]
    db.rollback()
    assert _plan(db) == [(1, 100, 0), (2, 200, 0)]


def test_plan_supplies_routing_even_without_legacy_account(db):
    service.create_rule(db, 1, schemas.CapsuleRuleCreate(
        capsule_id=1, trigger_type="Transfer", source_mode="fixed_account",
        source_account_id=2, amount_type="fixed", amount_value=100,
    ))
    entries = [schemas.TransactionLeg(account_id=1, debit=200),
               schemas.TransactionLeg(account_id=2, credit=200)]

    def preview():
        return service.capsule_transfer_specs(db, 1, entries=entries, description="Transfer", amount=200)

    before = preview()
    assert len(before) == 1
    assert (before[0].destination_account_id, before[0].amount) == (1, 100)
    service.set_funding_sources(db, 1, 1, [_input(2, 50)])
    # The plan now points at the source itself, so no movement is proposed.
    assert preview() == []
    service.set_funding_sources(db, 1, 1, [_input(1, 50)])
    db.get(models.Capsule, 1).account_id = None
    db.commit()
    assert preview() == before
    assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0


def test_http_round_trip_and_capsule_response_are_read_only(db, monkeypatch):
    app = FastAPI()
    app.include_router(router.router)
    app.add_exception_handler(DomainError, domain_error_handler)
    # Bind to the router's actual dependency modules: the suite supports both
    # app.* and backend.app.* import paths.
    app.dependency_overrides[router.database.get_db] = lambda: db
    app.dependency_overrides[router.dependencies.get_current_client] = lambda: db.get(models.Client, 1)
    async def request(http, method, path, **kwargs):
        # Match the GET guard's timer: sandbox selector wakeups can be lost.
        task = asyncio.create_task(http.request(method, path, **kwargs))
        deadline = asyncio.get_running_loop().time() + 30
        while not task.done():
            await asyncio.wait({task}, timeout=0.01)
            if asyncio.get_running_loop().time() >= deadline:
                task.cancel()
                pytest.fail(f"{method} {path} did not complete in 30 seconds")
        return task.result()

    async def round_trip():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
            response = await request(http, "PUT", "/capsules/1/funding-sources", json=[
                {"account_id": 1, "target_amount": 500, "sort_order": 1},
                {"account_id": 2, "target_amount": 900, "sort_order": 0},
            ])
            assert response.status_code == 200
            expected = response.json()
            assert [(r["account_id"], r["target_amount"]) for r in expected] == [(2, 900), (1, 500)]
            # Intent is allowed to differ from the capsule's target; no money moved.
            assert db.get(models.Capsule, 1).account_id == 1
            assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0
            for capsule_id in [2, 99999]:
                assert (await request(http, "PUT", f"/capsules/{capsule_id}/funding-sources", json=[])).status_code == 404
                assert (await request(http, "GET", f"/capsules/{capsule_id}/funding-sources")).status_code == 404

            def unexpected(*_args, **_kwargs):
                pytest.fail("Reading a funding plan must not write")

            monkeypatch.setattr(db, "flush", unexpected)
            monkeypatch.setattr(db, "commit", unexpected)
            monkeypatch.setattr(service, "invalidate_client", unexpected)
            response = await request(http, "GET", "/capsules/1/funding-sources")
            assert response.status_code == 200
            assert response.json() == expected
            response = await request(http, "GET", "/capsules/")
            assert response.status_code == 200
            assert response.json()[0]["funding_sources"] == expected
            assert response.json()[0]["current_balance"] == 0
            assert not db.new and not db.dirty and not db.deleted

    asyncio.run(round_trip())


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261013_0054_capsule_funding_sources.py"
    spec = importlib.util.spec_from_file_location("f1a_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _old_database():
    metadata = sa.MetaData()
    clients = sa.Table("clients", metadata, sa.Column("id", sa.Integer, primary_key=True))
    accounts = sa.Table("accounts", metadata, sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id")))
    capsules = sa.Table("capsules", metadata, sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id")),
                        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id")),
                        sa.Column("target_amount_minor", sa.BigInteger))
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(clients.insert(), [{"id": 1}, {"id": 2}])
        connection.execute(accounts.insert(), [{"id": i, "client_id": 1} for i in range(1, 14)]
                           + [{"id": 14, "client_id": 2}])
        connection.execute(capsules.insert(), [
            {"id": i, "client_id": 1, "account_id": i, "target_amount_minor": target}
            for i, target in enumerate(LIVE_TARGETS, 1)
        ] + [
            {"id": 13, "client_id": 1, "account_id": None, "target_amount_minor": 999},
            {"id": 14, "client_id": 1, "account_id": 13, "target_amount_minor": None},
            # A second client also gets a plan, with no currency conversion.
            {"id": 15, "client_id": 2, "account_id": 14, "target_amount_minor": 1234},
        ])
    return engine


def _run(engine, direction):
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN")
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_migration(), direction)()


def test_migration_seeds_live_targets_nulls_and_downgrades_cleanly():
    engine = _old_database()
    try:
        assert _migration().down_revision == "20261012_0053"
        _run(engine, "upgrade")
        inspector = sa.inspect(engine)
        assert inspector.get_unique_constraints("capsule_funding_sources")[0]["column_names"] == ["capsule_id", "account_id"]
        assert any(index["column_names"] == ["capsule_id"] for index in inspector.get_indexes("capsule_funding_sources"))
        assert next(col for col in inspector.get_columns("accounts") if col["name"] == "max_capsule_share_bp")["nullable"]
        with engine.connect() as connection:
            rows = list(connection.execute(sa.text("SELECT * FROM capsule_funding_sources ORDER BY capsule_id")).mappings())
            old_capsules = list(connection.execute(sa.text("SELECT * FROM capsules ORDER BY id")))
        assert len(rows) == 14
        assert [row["target_amount_minor"] for row in rows] == LIVE_TARGETS + [0, 1234]
        assert [row["client_id"] for row in rows] == [1] * 13 + [2]
        assert all(row["sort_order"] == 0 for row in rows)
        assert [row["account_id"] for row in rows] == list(range(1, 15))
        assert [row["capsule_id"] for row in rows] == list(range(1, 13)) + [14, 15]
        assert all(row["created_at"] and row["updated_at"] for row in rows)
        _run(engine, "downgrade")
        assert "capsule_funding_sources" not in sa.inspect(engine).get_table_names()
        assert "max_capsule_share_bp" not in {col["name"] for col in sa.inspect(engine).get_columns("accounts")}
        with engine.connect() as connection:
            assert list(connection.execute(sa.text("SELECT * FROM capsules ORDER BY id"))) == old_capsules
    finally:
        engine.dispose()


@pytest.mark.parametrize("damage,message", [("count", "count mismatch"), ("amount", "seed mismatch")])
def test_migration_verification_raises_and_rolls_back_on_bad_seed(damage, message):
    engine = _old_database()

    def corrupt_seed(connection, _cursor, statement, *_args):
        if statement.startswith("INSERT INTO capsule_funding_sources"):
            if damage == "count":
                connection.exec_driver_sql("DELETE FROM capsule_funding_sources WHERE capsule_id = 1")
            else:
                connection.exec_driver_sql("UPDATE capsule_funding_sources SET target_amount_minor = 1 WHERE capsule_id = 1")

    sa.event.listen(engine, "after_cursor_execute", corrupt_seed)
    try:
        with pytest.raises(ValueError, match=message):
            _run(engine, "upgrade")
        assert "capsule_funding_sources" not in sa.inspect(engine).get_table_names()
        assert "max_capsule_share_bp" not in {col["name"] for col in sa.inspect(engine).get_columns("accounts")}
    finally:
        sa.event.remove(engine, "after_cursor_execute", corrupt_seed)
        engine.dispose()
