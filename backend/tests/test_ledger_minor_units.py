from app.services.ledger_valuation import calculate_account_valued_balance
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, aliased
from sqlalchemy.pool import StaticPool

from backend.app import models, schemas
from backend.app.database import Base, get_db
from backend.app.dependencies import get_current_client
from backend.app.domain.journal import Leg, coerce_leg, validate_legs
from backend.app.domain.money import Money
from backend.app.routers.transactions import router
from backend.app.services import ledger_service as ledger
from backend.app.services.data_health_service import _unbalanced_journal_items
from backend.app.services.data_transfer_service import export_client, import_client


@pytest.fixture
def posting():
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        client = models.Client(id=1, name="B4 SQLite", general_settings={}, ai_config={})
        accounts = [models.Account(client_id=1, name=name, account_type=kind)
                    for name, kind in (("cash", "asset"), ("food", "expense"), ("advance", "asset"))]
        db.add_all([client, *accounts])
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_client] = lambda: client
        with TestClient(app) as http:
            yield db, client, accounts, http
    engine.dispose()


def _payload(accounts, currency, amount, first):
    cash, food, advance = accounts
    second = float(Money.from_major(str(amount), currency).to_major()
                   - Money.from_major(str(first), currency).to_major())
    return {
        "date": "2026-10-12", "description": "B4 round trip", "currency": currency, "amount": amount,
        "legs": [{"account_id": cash.id, "credit": amount},
                 {"account_id": food.id, "debit": first},
                 {"account_id": advance.id, "debit": second}],
    }


@pytest.mark.parametrize("currency,amount,first", [("JPY", 1051, 700), ("USD", 46.48, 30.12), ("EUR", 1050.95, 700.15)])
def test_http_round_trip_and_sql_reads(posting, currency, amount, first):
    db, _, accounts, http = posting
    payload = _payload(accounts, currency, amount, first)
    response = http.post("/transactions/", json=payload)
    assert response.status_code == 200, response.text
    posted = response.json()
    read = http.get("/transactions/", params={"amount_min": amount, "amount_max": amount}).json()[0]
    for result in (posted, read):
        assert result["amount"] == amount
        assert [(leg["debit"], leg["credit"]) for leg in result["legs"]] == [
            (leg.get("debit", 0), leg.get("credit", 0)) for leg in payload["legs"]]
    tx = db.get(models.Transaction, posted["id"])
    assert type(tx.amount_minor) is int
    assert tx.amount_minor == Money.from_major(str(amount), currency).minor
    assert sum(leg.debit_minor for leg in tx.journal_entries) == tx.amount_minor
    assert calculate_account_valued_balance(db, accounts[0], target_currency=currency) == -amount
    assert calculate_account_valued_balance(db, accounts[0], date(2026, 10, 12), target_currency=currency) == -amount
    assert not _unbalanced_journal_items(db, 1)
    for joined in (False, True):
        query = db.query(sa.func.sum(models.JournalEntry.debit), sa.func.sum(models.JournalEntry.credit))
        if joined:
            query = query.join(models.Transaction)
        assert query.one() == pytest.approx((amount, amount))
    entry_alias = aliased(models.JournalEntry)
    assert db.query(sa.func.sum(entry_alias.debit)).scalar() == pytest.approx(amount)
    print(f"API {currency}: POST amount={amount}, GET amount={read['amount']}, stored={tx.amount_minor}; legs={[(leg['debit'], leg['credit']) for leg in read['legs']]}")


@pytest.mark.parametrize("currency", ["JPY", "USD", "EUR"])
def test_proposal_response_and_approval_scale_once(posting, currency):
    db, _, accounts, http = posting
    payload = _payload(accounts, currency, 120 if currency == "JPY" else 12.63, 100 if currency == "JPY" else 10.01)
    proposal = ledger.propose_transaction(
        db, 1, origin="test", date=date(2026, 10, 12), description="Queued cents",
        amount_minor=Money.from_major(str(payload["amount"]), currency).minor,
        currency=currency, legs=payload["legs"],
    )
    db.commit()
    assert all(type(leg[side]) is int for leg in proposal.legs for side in ("debit", "credit"))
    wire = http.get("/transactions/proposals").json()[0]
    assert wire["amount"] == payload["amount"]
    assert wire["legs"][1]["debit"] == payload["legs"][1]["debit"]
    assert schemas.TransactionProposal.model_validate(proposal).model_dump()["legs"] == wire["legs"]
    approved = http.post(f"/transactions/proposals/{proposal.id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["amount"] == payload["amount"]
    assert approved.json()["legs"][1]["debit"] == payload["legs"][1]["debit"]
    assert calculate_account_valued_balance(db, accounts[0], target_currency=currency) == -payload["amount"]
    ledger.delete_transaction(db, db.get(models.Transaction, approved.json()["id"]))
    db.flush()
    assert calculate_account_valued_balance(db, accounts[0], target_currency=currency) == 0


@pytest.mark.parametrize("currency", ["JPY", "USD"])
def test_compound_integer_invariant(currency):
    legs = [Leg(1, debit=700), Leg(2, debit=351), Leg(3, credit=1051)]
    validate_legs(legs, 1051)
    with pytest.raises(ValueError, match="does not balance"):
        validate_legs([legs[0], legs[1], Leg(3, credit=1050)], 1051)
    with pytest.raises(ValueError, match="does not match"):
        validate_legs(legs, 1050)
    print(f"Invariant {currency}: 700 + 351 = 1051 passes; credit 1050 and header 1050 each fail (one {'yen' if currency == 'JPY' else 'cent'})")


def test_fractional_input_rounds_at_boundary_but_minor_storage_refuses(posting):
    db, _, accounts, http = posting
    payload = _payload(accounts, "USD", 1050.955, 700.95)
    response = http.post("/transactions/", json=payload)
    assert response.status_code == 200, response.text
    tx = db.get(models.Transaction, response.json()["id"])
    assert tx.amount_minor == 105096
    assert response.json()["amount"] == 1050.96
    assert coerce_leg({"account_id": 1, "debit": 1050.955}, "USD").debit == 105096
    tx.amount_minor = 1050.955
    with pytest.raises(sa.exc.StatementError, match="minor units must be a plain integer"):
        db.flush()
    db.rollback()
    assert db.get(models.Transaction, response.json()["id"]).amount_minor == 105096
    with pytest.raises(TypeError, match="integer minor units"):
        Leg(1, debit=1050.955)
    print("Fractional USD 1050.955: HTTP -> 105096 minor -> wire 1050.96 (Money ROUND_HALF_UP); direct amount_minor=1050.955 refuses at SQLAlchemy bind")


@pytest.mark.parametrize("model,name", [(models.Transaction, "amount"), (models.TransactionProposal, "amount"), (models.JournalEntry, "debit"), (models.JournalEntry, "credit")])
def test_major_hybrids_have_no_setter(model, name):
    with pytest.raises(AttributeError):
        setattr(model(), name, 1.23)


@pytest.mark.parametrize("currency", ["JPY", "USD"])
def test_update_keeps_currency_and_journal_balance(posting, currency):
    db, _, accounts, http = posting
    payload = _payload(accounts, currency, 120 if currency == "JPY" else 12.63, 100 if currency == "JPY" else 10.01)
    tx_id = http.post("/transactions/", json=payload).json()["id"]
    response = http.put(f"/transactions/{tx_id}", json={"description": "Retain cents"})
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == payload["amount"]
    assert response.json()["legs"][1]["debit"] == payload["legs"][1]["debit"]
    assert calculate_account_valued_balance(db, accounts[0], target_currency=currency) == -payload["amount"]


@pytest.mark.parametrize("currency,amount,first", [("JPY", 1051, 700), ("USD", 46.48, 30.12), ("EUR", 1050.95, 700.15)])
def test_export_import_keeps_major_wire_and_integer_storage(posting, currency, amount, first):
    db, client, accounts, http = posting
    response = http.post("/transactions/", json=_payload(accounts, currency, amount, first))
    assert response.status_code == 200
    document = export_client(db, client)
    assert document["data"]["transactions"][0]["amount"] == amount
    target = models.Client(id=2, name="B4 import target", general_settings={}, ai_config={})
    db.add(target)
    db.commit()
    import_client(db, target, data=document["data"], version=document["version"], manifest=document["manifest"])
    restored = db.query(models.Transaction).filter_by(client_id=2).one()
    assert restored.amount_minor == Money.from_major(str(amount), currency).minor
    assert sorted((leg.debit_minor, leg.credit_minor) for leg in restored.journal_entries) == sorted(
        (leg.debit_minor, leg.credit_minor) for leg in db.query(models.Transaction).filter_by(client_id=1).one().journal_entries)


def test_currency_change_rescales_retained_compound_legs_and_balance(posting):
    currency = "USD"
    db, _, accounts, http = posting
    tx_id = http.post("/transactions/", json=_payload(accounts, "JPY", 120, 100)).json()["id"]
    response = http.put(f"/transactions/{tx_id}", json={"currency": "USD"})
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == 120
    tx = db.get(models.Transaction, tx_id)
    assert tx.amount_minor == 12000
    assert sorted(leg.debit_minor for leg in tx.journal_entries) == [0, 2000, 10000]
    assert calculate_account_valued_balance(db, accounts[0], target_currency=currency) == -120


def test_proposal_key_keeps_major_float_encoding(posting):
    db, _, accounts, _ = posting
    payload = _payload(accounts, "USD", 46.48, 30.12)
    prior = {
        "origin": "test", "origin_ref": {}, "date": "2026-10-12", "amount": 46.48,
        "legs": [{**leg, "debit": float(leg.get("debit", 0)), "credit": float(leg.get("credit", 0)), "memo": None} for leg in payload["legs"]],
    }
    prior_key = hashlib.sha256(json.dumps(prior, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    proposal = ledger.propose_transaction(db, 1, origin="test", date=date(2026, 10, 12),
        description="Keep key", amount_minor=4648, currency="USD", legs=payload["legs"])
    assert proposal.idempotency_key == prior_key


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261012_0051_ledger_minor_units.py"
    spec = importlib.util.spec_from_file_location("b4_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_database():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    transactions = sa.Table("transactions", metadata,
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("currency", sa.String), sa.Column("amount", sa.Float))
    entries = sa.Table("journal_entries", metadata,
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("transaction_id", sa.Integer, sa.ForeignKey("transactions.id")),
        sa.Column("debit", sa.Float), sa.Column("credit", sa.Float))
    proposals = sa.Table("transaction_proposals", metadata,
        sa.Column("id", sa.Integer, primary_key=True), sa.Column("currency", sa.String, nullable=False),
        sa.Column("amount", sa.Float, nullable=False), sa.Column("legs", sa.JSON, nullable=False))
    metadata.create_all(engine)
    rows = [(1, "JPY", 5162192), (2, "USD", 46.48), (3, "EUR", 1050.95)]
    with engine.begin() as connection:
        for row_id, currency, amount in rows:
            connection.execute(transactions.insert().values(id=row_id, currency=currency, amount=amount))
            connection.execute(entries.insert(), [
                {"id": row_id * 2, "transaction_id": row_id, "debit": amount, "credit": 0},
                {"id": row_id * 2 + 1, "transaction_id": row_id, "debit": 0, "credit": amount},
            ])
            connection.execute(proposals.insert().values(id=row_id, currency=currency, amount=amount, legs=[
                {"account_id": 1, "debit": amount, "credit": 0, "memo": "preserve"},
                {"account_id": 2, "debit": 0, "credit": amount},
            ]))
    return engine, rows


def _run_migration(engine, direction):
    with engine.begin() as connection:
        # SQLite otherwise delays BEGIN until DML, leaving failed DDL outside rollback.
        connection.exec_driver_sql("BEGIN")
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_migration(), direction)()


def _snapshot(engine):
    with engine.connect() as connection:
        metadata = sa.MetaData()
        tables = [sa.Table(name, metadata, autoload_with=connection) for name in
                  ("transactions", "journal_entries", "transaction_proposals")]
        return [[dict(row) for row in connection.execute(sa.select(table).order_by(table.c.id)).mappings()]
                for table in tables]


def test_migration_applies_and_reverses_losslessly():
    engine, rows = _legacy_database()
    before = _snapshot(engine)
    _run_migration(engine, "upgrade")
    after = _snapshot(engine)
    assert [row["amount_minor"] for row in after[0]] == [5162192, 4648, 105095]
    assert all(type(row["debit_minor"]) is int and type(row["credit_minor"]) is int for row in after[1])
    assert all(type(leg[side]) is int for row in after[2] for leg in row["legs"] for side in ("debit", "credit"))
    with engine.connect() as connection:
        for table, names in (("transactions", ("amount_minor",)), ("journal_entries", ("debit_minor", "credit_minor")), ("transaction_proposals", ("amount_minor",))):
            columns = {column["name"]: column for column in sa.inspect(connection).get_columns(table)}
            assert all(not columns[name]["nullable"] and isinstance(columns[name]["type"], sa.BigInteger) for name in names)
    _run_migration(engine, "downgrade")
    restored = _snapshot(engine)
    assert restored == before
    for original, converted, reversed_row in zip(before[0], after[0], restored[0]):
        print(f"Migration {original['currency']}: {original['amount']} -> {converted['amount_minor']} -> {reversed_row['amount']}")
    print(f"Migration legs before={before[1]}, after={after[1]}, reversed={restored[1]}")
    engine.dispose()


@pytest.mark.parametrize("damage,message", [("currency", "Unsupported currency"), ("sides", "journal invariant"), ("amount", "journal invariant"), ("missing", "journal invariant"), ("fraction", "Lossy"), ("proposal", "does not balance")])
def test_migration_refuses_and_rolls_back(damage, message):
    engine, _ = _legacy_database()
    sql = {
        "currency": "UPDATE transactions SET currency = 'GBP' WHERE id = 2",
        "sides": "UPDATE journal_entries SET debit = 46.47 WHERE id = 4",
        "amount": "UPDATE transactions SET amount = 46.49 WHERE id = 2",
        "missing": "DELETE FROM journal_entries WHERE transaction_id = 2",
        "fraction": "UPDATE transactions SET amount = 46.485 WHERE id = 2",
        "proposal": "UPDATE transaction_proposals SET legs = '[{\"account_id\":1,\"debit\":46.47,\"credit\":0},{\"account_id\":2,\"debit\":0,\"credit\":46.48}]' WHERE id = 2",
    }[damage]
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)
    before = _snapshot(engine)
    with pytest.raises(ValueError, match=message):
        _run_migration(engine, "upgrade")
    assert _snapshot(engine) == before
    engine.dispose()


def test_downgrade_refuses_float_precision_loss():
    engine, _ = _legacy_database()
    _run_migration(engine, "upgrade")
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE transactions SET amount_minor = 9007199254740993 WHERE id = 1")
    before = _snapshot(engine)
    with pytest.raises(ValueError, match="Lossy downgrade"):
        _run_migration(engine, "downgrade")
    assert _snapshot(engine) == before
    engine.dispose()
