"""F2a: the earmark is an attributed leg, independently of proposals or plans."""
from datetime import date
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.domain.journal import Leg, coerce_leg
from app.domain.transfer import validate_import_payload
from app.routers.transactions import _serialize_transaction
from app.services import capsule_service as capsule, ledger_service as ledger
from app.services.analysis_service import _sum_capsule_balance
from app.services.data_health_service import check_data_health
from app.services.data_transfer_service import export_client, import_client

WHEN = date(2026, 10, 12)


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([
            models.Client(id=i, name=f"Client {i}", general_settings={"currency": "JPY"})
            for i in [1, 2]
        ])
        session.flush()
        session.add_all([
            models.Account(id=i, client_id=1 if i < 4 else 2, name=f"Account {i}", account_type="asset")
            for i in [1, 2, 3, 4, 5]
        ])
        session.add_all([
            models.Capsule(id=i, client_id=1 if i < 3 else 2, name=f"Capsule {i}",
                           funding_sources=[models.CapsuleFundingSource(client_id=1 if i < 3 else 2, account_id=2 if i < 3 else 4, target_amount_minor=1000)], target_amount_minor=1000,
                           monthly_contribution_minor=0)
            for i in [1, 2, 3]
        ])
        session.commit()
        yield session
    engine.dispose()


def post(db, amount, legs, *, currency="JPY", client_id=1):
    tx = ledger.create_transaction(db, client_id=client_id, date=WHEN, description="Manual entry",
                                   amount_minor=amount, currency=currency, legs=legs)
    db.flush()
    return tx


def test_manual_transfer_and_credit_release_need_no_proposal(db):
    schema = schemas.TransactionLeg(account_id=2, debit=300, capsule_id=1, memo="PC")
    assert coerce_leg(schema, "JPY") == coerce_leg(schema.model_dump(), "JPY") == Leg(2, 300, memo="PC", capsule_id=1)
    tx = post(db, 300, [schema, schemas.TransactionLeg(account_id=1, credit=300)])
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 300}
    assert [(leg["capsule_id"], leg["memo"]) for leg in _serialize_transaction(tx)["legs"]] == [(1, "PC"), (None, None)]
    post(db, 125, [Leg(1, debit=125), Leg(2, credit=125, capsule_id=1)])
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 175}
    assert db.query(models.TransactionProposal).count() == 0
    post(db, 200, [Leg(1, debit=200), Leg(2, credit=200, capsule_id=1)])
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": -25}


def test_one_split_entry_attributes_two_capsules_separately(db):
    tx = post(db, 450, [Leg(2, debit=150, capsule_id=1), Leg(3, debit=300, capsule_id=2), Leg(1, credit=450)])
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 150}
    assert capsule.claimed_minor(db, 1, 2) == {"JPY": 300}
    assert len(tx.journal_entries) == 3
    assert db.query(models.Transaction).count() == 1


@pytest.mark.parametrize("foreign_id", [3, 999])
@pytest.mark.parametrize("operation", ["create", "propose"])
def test_foreign_or_missing_capsule_is_refused_before_any_write(db, foreign_id, operation):
    legs = [Leg(2, debit=100, capsule_id=1), Leg(3, debit=100, capsule_id=foreign_id), Leg(1, credit=200)]
    with pytest.raises(ValueError, match=f"Capsule {foreign_id} not found for this client"):
        if operation == "create":
            post(db, 200, legs)
        else:
            ledger.propose_transaction(db, 1, origin="manual", date=WHEN, description="Invalid",
                                       amount_minor=200, currency="JPY", legs=legs)
    assert not db.new and not db.dirty and not db.deleted
    for model in [models.Transaction, models.JournalEntry, models.TransactionProposal]:
        assert db.query(model).count() == 0


def test_claims_are_per_currency_per_account_and_client_scoped(db):
    post(db, 300, [Leg(2, debit=100, capsule_id=1), Leg(3, debit=200, capsule_id=1), Leg(1, credit=300)])
    post(db, 12345, [Leg(2, debit=12345, capsule_id=1), Leg(1, credit=12345)], currency="USD")
    post(db, 77, [Leg(4, debit=77, capsule_id=3), Leg(5, credit=77)], client_id=2)
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 300, "USD": 12345}
    assert capsule.claimed_minor(db, 1, 1, 2) == {"JPY": 100, "USD": 12345}
    assert capsule.claimed_minor(db, 1, 1, 3) == {"JPY": 200}
    assert capsule.claimed_minor(db, 1, 1, 1) == {}
    assert capsule.claimed_minor(db, 2, 1) == capsule.claimed_minor(db, 1, 3) == {}
    assert capsule.claimed_minor(db, 2, 3) == {"JPY": 77}


def test_balances_and_response_read_claim(db):
    owner = db.get(models.Capsule, 1)
    post(db, 300, [Leg(2, debit=300, capsule_id=1), Leg(1, credit=300)])
    post(db, 12000, [Leg(3, debit=12000, capsule_id=1), Leg(1, credit=12000)], currency="USD")
    db.commit()
    assert capsule.capsule_balance(db, owner) == 300
    assert capsule.remaining_target(db, owner) == 700
    assert capsule.capsule_to_dict(db, owner)["current_balance"] == 300
    capsule.update_capsule(db, 1, 1, schemas.CapsuleUpdate(name="PC", current_balance=9999))
    db.commit()
    db.expire_all()
    assert capsule.capsule_to_dict(db, owner)["current_balance"] == 300


@pytest.mark.parametrize("patch", [
    {"description": "Edited"}, {"amount": 200}, {"currency": "USD"},
])
def test_amendment_preserves_leg_attribution_and_memo(db, patch):
    tx = post(db, 100, [Leg(2, debit=100, capsule_id=1, memo="PC"), Leg(1, credit=100, memo="Source")])
    db.commit()
    ledger.update_transaction(db, tx.id, schemas.TransactionUpdate(**patch), 1)
    legs = db.query(models.JournalEntry).filter_by(transaction_id=tx.id).order_by(models.JournalEntry.sort_order).all()
    assert [(leg.capsule_id, leg.memo) for leg in legs] == [(1, "PC"), (None, "Source")]
    currency = patch.get("currency", "JPY")
    assert capsule.claimed_minor(db, 1, 1) == {currency: 10000 if currency == "USD" else patch.get("amount", 100)}


def test_shared_account_total_is_the_sum_of_claims_not_its_balance(db):
    post(db, 10000, [Leg(2, debit=10000), Leg(1, credit=10000)])
    post(db, 500, [Leg(2, debit=200, capsule_id=1), Leg(2, debit=300, capsule_id=2), Leg(1, credit=500)])
    assert _sum_capsule_balance(db, 1) == 500
    assert _sum_capsule_balance(db, 2) == 0


def test_deleting_capsule_nulls_attribution_preserves_money_and_history(db):
    post(db, 300, [Leg(2, debit=300, capsule_id=1), Leg(1, credit=300)])
    post(db, 50, [Leg(1, debit=50), Leg(2, credit=50, capsule_id=1)])
    post(db, 100, [Leg(2, debit=100, capsule_id=2), Leg(1, credit=100)])
    db.commit()
    before = [(leg.id, leg.transaction_id, leg.account_id, leg.debit_minor, leg.credit_minor)
              for leg in db.query(models.JournalEntry).order_by(models.JournalEntry.id)]
    capsule.delete_capsule(db, 1, 1)
    db.expire_all()
    after = [(leg.id, leg.transaction_id, leg.account_id, leg.debit_minor, leg.credit_minor)
             for leg in db.query(models.JournalEntry).order_by(models.JournalEntry.id)]
    assert before == after
    assert db.query(models.Transaction).count() == 3
    assert [leg.capsule_id for leg in db.query(models.JournalEntry).order_by(models.JournalEntry.id)] == [None, None, None, None, 2, None]
    assert capsule.claimed_minor(db, 1, 1) == {}
    assert capsule.claimed_minor(db, 1, 2) == {"JPY": 100}


def test_backup_round_trip_remaps_attributed_legs_and_ignores_legacy_cache(db):
    post(db, 450, [Leg(2, debit=150, capsule_id=1), Leg(3, debit=300, capsule_id=2), Leg(1, credit=450)])
    post(db, 50, [Leg(1, debit=50), Leg(2, credit=50, capsule_id=1)])
    post(db, 12345, [Leg(2, debit=12345, capsule_id=1), Leg(1, credit=12345)], currency="USD")
    db.commit()
    document = json.loads(json.dumps(export_client(db, db.get(models.Client, 1))))
    assert document["data"]["journal_entries"][0]["capsule_id"] == 1
    assert "current_balance" not in document["data"]["capsules"][0]
    document["data"]["capsules"][0]["current_balance"] = 999999
    assert validate_import_payload(document["data"])["error_count"] == 0
    target = db.get(models.Client, 2)
    import_client(db, target, data=document["data"], version=document["version"], manifest=document["manifest"])
    restored = {owner.name: owner for owner in db.query(models.Capsule).filter_by(client_id=2)}
    first, second = restored["Capsule 1"], restored["Capsule 2"]
    assert first.id != 1 and second.id != 2
    assert capsule.claimed_minor(db, 2, first.id) == {"JPY": 100, "USD": 12345}
    assert capsule.claimed_minor(db, 2, second.id) == {"JPY": 300}
    assert capsule.claimed_minor(db, 1, 1) == {"JPY": 100, "USD": 12345}


def test_backup_validation_refuses_unknown_capsule_reference(db):
    post(db, 100, [Leg(2, debit=100, capsule_id=1), Leg(1, credit=100)])
    db.commit()
    data = export_client(db, db.get(models.Client, 1))["data"]
    data["journal_entries"][0]["capsule_id"] = 999
    result = validate_import_payload(data)
    assert any(issue.get("collection") == "journal_entries" and issue.get("field") == "capsule_id"
               and issue["code"] == "missing_reference" for issue in result["issues"])


def test_health_checks_missing_funding_plan(db):
    owner = db.get(models.Capsule, 1)
    owner.funding_sources = []
    db.add(models.CapsuleRule(client_id=1, capsule_id=1, trigger_type="Income", amount_type="fixed", amount_minor=100, is_active=True))
    db.commit()
    issue = next(issue for issue in check_data_health(db, 1)["issues"] if issue["code"] == "capsule_without_account")
    assert issue["count"] == 1
    capsule.set_funding_sources(db, 1, 1, [schemas.CapsuleFundingSourceInput(account_id=2, target_amount=1000)])
    issue = next(issue for issue in check_data_health(db, 1)["issues"] if issue["code"] == "capsule_without_account")
    assert issue["count"] == 0


def test_migration_both_directions_preserve_all_old_legs_without_backfill():
    path = Path(__file__).parents[1] / "alembic/versions/20261013_0056_journal_capsule_attribution.py"
    spec = importlib.util.spec_from_file_location("f2a_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261013_0056"
    assert migration.down_revision == "20261013_0055"
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("capsules", metadata, sa.Column("id", sa.Integer, primary_key=True))
    old = sa.Table("journal_entries", metadata, sa.Column("id", sa.Integer, primary_key=True),
                   sa.Column("debit_minor", sa.BigInteger), sa.Column("credit_minor", sa.BigInteger))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(old.insert(), [{"id": i, "debit_minor": i, "credit_minor": 0} for i in range(1, 888)])

    def run(direction):
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                getattr(migration, direction)()

    try:
        run("upgrade")
        inspector = sa.inspect(engine)
        assert next(column for column in inspector.get_columns("journal_entries") if column["name"] == "capsule_id")["nullable"]
        fk = inspector.get_foreign_keys("journal_entries")[0]
        assert (fk["constrained_columns"], fk["referred_table"], fk["referred_columns"], fk["options"]) == (["capsule_id"], "capsules", ["id"], {"ondelete": "SET NULL"})
        assert any(index["column_names"] == ["capsule_id"] for index in inspector.get_indexes("journal_entries"))
        with engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM journal_entries WHERE capsule_id IS NULL").scalar() == 887
            connection.exec_driver_sql("INSERT INTO capsules (id) VALUES (1)")
            connection.exec_driver_sql("UPDATE journal_entries SET capsule_id = 1 WHERE id = 1")
        run("downgrade")
        assert "capsule_id" not in {column["name"] for column in sa.inspect(engine).get_columns("journal_entries")}
        assert not sa.inspect(engine).get_indexes("journal_entries")
        assert not sa.inspect(engine).get_foreign_keys("journal_entries")
        with engine.connect() as connection:
            assert list(connection.execute(old.select().order_by(old.c.id))) == [(i, i, 0) for i in range(1, 888)]
        run("upgrade")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM journal_entries WHERE capsule_id IS NULL").scalar() == 887
    finally:
        engine.dispose()
