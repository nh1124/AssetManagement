"""F2c removes the old mechanism without discarding claims or journal facts."""
import asyncio
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
import httpx
import pytest
import sqlalchemy as sa

from app import dependencies, models, schemas
from app.database import Base
from app.routers import capsules as router
from app.services import capsule_service as service
from app.services.data_transfer_service import export_client, import_client
from app.workflows.capsule_workflow import contribute
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"}, ai_config={}) for i in [1, 2]])
        session.commit()
        yield session
    engine.dispose()


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261013_0057_retire_capsule_holdings.py"
    spec = importlib.util.spec_from_file_location("f2c_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def old_database(*, holding=False):
    metadata = sa.MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    metadata.tables["capsules"].append_column(sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id")))
    metadata.tables["capsules"].append_column(sa.Column("current_balance_minor", sa.BigInteger, default=0))
    sa.Table("capsule_holdings", metadata,
             sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("capsule_id", sa.Integer, sa.ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False),
             sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
             sa.Column("held_amount_minor", sa.BigInteger, nullable=False, server_default="0"),
             sa.Column("note", sa.String), sa.Column("updated_at", sa.DateTime))
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(metadata.tables["clients"].insert(), {"id": 1, "name": "scratch", "general_settings": {}, "ai_config": {}})
        connection.execute(metadata.tables["accounts"].insert(), [
            {"id": i, "client_id": 1, "name": str(i), "account_type": "asset"} for i in [1, 2, 3]])
        connection.execute(metadata.tables["capsules"].insert(), [
            {"id": i, "client_id": 1, "name": str(i), "account_id": 1, "current_balance_minor": 0} for i in [1, 2, 3]])
        connection.execute(metadata.tables["capsule_funding_sources"].insert(), [
            {"id": 1, "client_id": 1, "capsule_id": 1, "account_id": 1, "sort_order": 5},
            {"id": 2, "client_id": 1, "capsule_id": 1, "account_id": 2, "sort_order": 0},
            {"id": 3, "client_id": 1, "capsule_id": 2, "account_id": 3, "sort_order": 0},
            {"id": 4, "client_id": 1, "capsule_id": 2, "account_id": 2, "sort_order": 0},
            {"id": 5, "client_id": 1, "capsule_id": 3, "account_id": 1, "sort_order": -1},
        ])
        if holding:
            connection.execute(metadata.tables["capsule_holdings"].insert(),
                               {"id": 1, "capsule_id": 1, "account_id": 1, "held_amount_minor": 17})
    return engine


def run(engine, direction):
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN")
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration(), direction)()


def snapshot(engine):
    metadata = sa.MetaData()
    metadata.reflect(engine)
    with engine.connect() as connection:
        return {name: ([(c.name, str(c.type), c.nullable) for c in table.columns],
                       list(connection.execute(table.select().order_by(table.c.id))))
                for name, table in metadata.tables.items()}


def test_migration_both_directions_restore_lowest_sorted_source_zero_cache_and_empty_table():
    engine = old_database()
    before = snapshot(engine)
    run(engine, "upgrade")
    upgraded = snapshot(engine)
    assert "capsule_holdings" not in upgraded
    assert {c[0] for c in upgraded["capsules"][0]}.isdisjoint({"account_id", "current_balance_minor"})
    assert len(upgraded["capsules"][1]) == 3
    for name in set(before) - {"capsules", "capsule_holdings"}:
        assert upgraded[name] == before[name]
    run(engine, "downgrade")
    with engine.connect() as connection:
        assert list(connection.execute(sa.text("SELECT id, account_id, current_balance_minor FROM capsules ORDER BY id"))) == [(1, 2, 0), (2, 3, 0), (3, 1, 0)]
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM capsule_holdings")) == 0
    assert {c[0] for c in snapshot(engine)["capsule_holdings"][0]} == {c[0] for c in before["capsule_holdings"][0]}
    run(engine, "upgrade")
    assert snapshot(engine) == upgraded


@pytest.mark.parametrize("held_minor", [0, 17])
def test_migration_refuses_any_holding_before_changing_schema_or_data(held_minor):
    engine = old_database(holding=True)
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE capsule_holdings SET held_amount_minor = :amount"), {"amount": held_minor})
    before = snapshot(engine)
    with pytest.raises(ValueError, match="Refusing to discard 1 capsule holding"):
        run(engine, "upgrade")
    assert snapshot(engine) == before


def seed_accounts(db):
    accounts = [models.Account(client_id=1, name=name, account_type="asset") for name in ["cash", "one", "two"]]
    db.add_all(accounts)
    db.commit()
    return accounts


def test_compatibility_create_seeds_full_target_and_list_reports_journal_claim(db):
    cash, one, _ = seed_accounts(db)
    owner = service.create_capsule(db, 1, schemas.CapsuleCreate(
        name="PC", target_amount=1001, monthly_contribution=10, account_id=one.id))
    assert [(s.account_id, s.target_amount_minor) for s in owner.funding_sources] == [(one.id, 1001)]
    assert service.capsule_to_dict(db, owner)["current_balance"] == 0
    contribute(db, 1, owner.id, amount=101, from_account_id=cash.id)
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[dependencies.get_db] = lambda: db
    client = db.get(models.Client, 1)
    app.dependency_overrides[dependencies.get_current_client] = lambda: client

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            response = await http.get("/capsules/")
            assert response.status_code == 200
            row = response.json()[0]
            assert row["current_balance"] == 101
            assert "holdings" not in row and "account_id" not in row
    asyncio.run(request())


def test_contribute_allocates_exact_parts_and_attributes_each_destination(db):
    cash, one, two = seed_accounts(db)
    owner = service.create_capsule(db, 1, schemas.CapsuleCreate(name="PC", target_amount=1001, monthly_contribution=10))
    service.set_funding_sources(db, 1, owner.id, [
        schemas.CapsuleFundingSourceInput(account_id=two.id, target_amount=2, sort_order=1),
        schemas.CapsuleFundingSourceInput(account_id=one.id, target_amount=1, sort_order=0)])
    assert contribute(db, 1, owner.id, amount=1001, from_account_id=cash.id) == {"status": "ok", "amount": 1001, "new_balance": 1001}
    assert db.query(models.Transaction).count() == 1
    legs = db.query(models.JournalEntry).order_by(models.JournalEntry.sort_order).all()
    assert [(leg.account_id, leg.debit_minor, leg.credit_minor, leg.capsule_id) for leg in legs] == [
        (one.id, 334, 0, owner.id), (two.id, 667, 0, owner.id), (cash.id, 0, 1001, None)]
    assert sum(leg.debit_minor for leg in legs) == sum(leg.credit_minor for leg in legs) == 1001
    assert service.claimed_minor(db, 1, owner.id, one.id) == {"JPY": 334}
    assert service.claimed_minor(db, 1, owner.id, two.id) == {"JPY": 667}


@pytest.mark.parametrize("method,path", [
    ("GET", "/capsules/{capsule_id}/holdings"), ("POST", "/capsules/{capsule_id}/holdings"),
    ("PUT", "/capsules/{capsule_id}/holdings/{holding_id}"), ("DELETE", "/capsules/{capsule_id}/holdings/{holding_id}")])
def test_retired_holding_routes_are_absent(method, path):
    assert not any(route.path == path and method in route.methods for route in router.router.routes)


@pytest.mark.parametrize("with_manifest", [False, True])
def test_v10_legacy_collection_warns_and_retired_capsule_fields_are_ignored(db, with_manifest):
    _, one, _ = seed_accounts(db)
    owner = service.create_capsule(db, 1, schemas.CapsuleCreate(name="PC", target_amount=1001, monthly_contribution=10, account_id=one.id))
    document = json.loads(json.dumps(export_client(db, db.get(models.Client, 1))))
    assert document["version"] == 17
    assert "capsule_holdings" not in document["data"]
    row = document["data"]["capsules"][0]
    assert "current_balance" not in row and "account_id" not in row
    row.update(account_id=999999, current_balance=999999)
    document["data"]["capsule_holdings"] = [{"id": 9, "capsule_id": 999999, "account_id": 999999, "held_amount": 999999}]
    manifest = None
    if with_manifest:
        from app.domain.transfer import _sha256, _table_checksums, data_counts
        checksums = {**_table_checksums(document["data"]), "capsule_holdings": _sha256(document["data"]["capsule_holdings"])}
        manifest = {"counts": {**data_counts(document["data"]), "capsule_holdings": 1},
                    "checksums": checksums, "payload_checksum": _sha256({"data": document["data"], "checksums": checksums})}
    result = import_client(db, db.get(models.Client, 2), data=document["data"], version=10, manifest=manifest)
    restored = db.query(models.Capsule).filter_by(client_id=2, name=owner.name).one()
    assert service.claimed_minor(db, 2, restored.id) == {}
    assert len(restored.funding_sources) == 1
    assert result["validation"]["error_count"] == 0
    assert {issue["code"] for issue in result["validation"]["issues"]} == ({"unknown_collection", "older_version", "payload_checksum_mismatch"}
                                                                                          if with_manifest else {"unknown_collection", "older_version"})


def test_strategy_uses_account_claims_for_funding_and_weighted_return(db):
    from datetime import date
    from app.domain.journal import Leg
    from app.services.ledger_service import create_transaction
    from app.services.strategy_service import calculate_current_funded_and_weighted_return
    cash, one, two = seed_accounts(db)
    one.expected_return, two.expected_return = 2, 8
    goal = models.LifeEvent(client_id=1, name="PC", target_amount_minor=1000, target_date=date(2027, 1, 1))
    db.add(goal)
    db.flush()
    owner = service.create_capsule_for_goal(db, 1, goal)
    create_transaction(db, client_id=1, date=date(2026, 10, 12), description="Claims",
                       amount_minor=400, currency="JPY",
                       legs=[Leg(one.id, debit=100, capsule_id=owner.id),
                             Leg(two.id, debit=300, capsule_id=owner.id), Leg(cash.id, credit=400)])
    create_transaction(db, client_id=1, date=date(2026, 10, 12), description="Foreign claim",
                       amount_minor=99999, currency="USD",
                       legs=[Leg(one.id, debit=99999, capsule_id=owner.id), Leg(cash.id, credit=99999)])
    db.commit()
    assert calculate_current_funded_and_weighted_return(goal, db) == (400, 6.5)
    assert calculate_current_funded_and_weighted_return(goal) == (400, 6.5)
    # Historical claim accounts still determine the return after a plan change.
    service.set_funding_sources(db, 1, owner.id, [schemas.CapsuleFundingSourceInput(account_id=cash.id, target_amount=1000)])
    assert calculate_current_funded_and_weighted_return(goal, db) == (400, 6.5)
