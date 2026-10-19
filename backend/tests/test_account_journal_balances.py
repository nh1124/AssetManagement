from contextlib import contextmanager
from datetime import date
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, aliased
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.money import Money
from app.domain.transfer import build_manifest
from app.models.money import MinorUnits
from app.routers import accounts as router
from app.services import ledger_service as ledger
from app.services.data_transfer_service import export_client, import_client
from app.services.ledger_valuation import calculate_account_balances, calculate_account_valued_balances

DAY = date(2026, 10, 12)
SETTINGS = ("liability_minimum_payment", "liability_fixed_payment_amount")


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(models.Client(id=1, name="B5", general_settings={"currency": "JPY"}))
        session.commit()
        yield session
    engine.dispose()


def _account(db, name, kind="asset"):
    return ledger.create_account(db, 1, {"name": name, "account_type": kind})


def _post(db, source, target, minor, currency="JPY", day=DAY):
    tx = ledger.create_transaction(
        db, client_id=1, date=day, description="B5 demonstration", amount_minor=minor,
        currency=currency, from_account_id=source.id, to_account_id=target.id,
    )
    db.commit()
    return tx


def test_multicurrency_exact_holdings_and_valued_http_response(db):
    wallet, income = _account(db, "wallet"), _account(db, "income", "income")
    for currency, minor, rate in (("EUR", 112419, 160.0), ("USD", 23248, 150.0)):
        db.add(models.ExchangeRate(client_id=1, base_currency=currency, quote_currency="JPY",
                                   rate=rate, as_of_date=DAY))
        db.commit()
        _post(db, income, wallet, minor, currency)
    queries = []

    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT") and "FROM journal_entries" in statement:
            queries.append(statement)

    with _capture(db.bind, capture):
        results = calculate_account_balances(db, [wallet, income])
    assert len(queries) == 1
    expected = 1124.19 * 160 + 232.48 * 150
    assert results[wallet.id].balances_minor == {"EUR": 112419, "USD": 23248}
    assert all(type(value) is int for value in results[wallet.id].balances_minor.values())
    assert results[wallet.id].balance == expected
    assert calculate_account_valued_balances(db, [wallet])[wallet.id] == expected

    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)
    with TestClient(app) as http:
        response = http.get("/accounts/")
    assert response.status_code == 200
    row = next(row for row in response.json() if row["id"] == wallet.id)
    assert row == {
        "id": wallet.id, "name": "wallet", "account_type": "asset", "balance": expected,
        "balances_minor": {"EUR": 112419, "USD": 23248},
        "liability_closing_day": None, "liability_payment_day": None,
        "liability_payment_month_offset": 0, "liability_payment_policy": "full",
        "liability_minimum_payment": None, "liability_fixed_payment_amount": None,
        "liability_installment_months": None, "liability_revolving_rate": None, "is_active": True,
    }
    print(f"EUR 112419 + USD 23248 minor; JPY valuation {expected} at rates 160 / 150; one journal query")


@contextmanager
def _capture(engine, callback):
    sa.event.listen(engine, "before_cursor_execute", callback)
    try:
        yield
    finally:
        sa.event.remove(engine, "before_cursor_execute", callback)


@pytest.mark.parametrize("kind", ["asset", "liability"])
@pytest.mark.parametrize("currency", ["JPY", "USD"])
def test_single_currency_agrees_with_old_journal_sum(db, kind, currency):
    client = db.get(models.Client, 1)
    client.general_settings = {"currency": currency}
    account, other = _account(db, kind, kind), _account(db, "other", "income")
    scale = Money.from_major("1", currency).minor
    if kind == "asset":
        _post(db, other, account, 1000 * scale, currency)
        _post(db, account, other, 250 * scale, currency)
    else:
        _post(db, account, other, 1000 * scale, currency)
        _post(db, other, account, 250 * scale, currency)
    debit, credit = db.query(sa.func.sum(models.JournalEntry.debit), sa.func.sum(models.JournalEntry.credit)).filter(
        models.JournalEntry.account_id == account.id,
    ).one()
    old = debit - credit if kind == "asset" else credit - debit
    new = calculate_account_balances(db, [account])[account.id]
    assert old == new.balance == 750.0
    assert new.balances_minor == {currency: 750 * scale}
    print(f"{kind} {currency}: old journal balance {old} == new {new.balance}")


def test_post_update_and_delete_never_write_any_account_column(db):
    source = _account(db, "card", "liability")
    target = ledger.create_account(db, 1, {
        "name": "bank", "account_type": "asset",
    })
    ledger.update_account(db, 1, source.id, {
        "liability_minimum_payment": 1000, "liability_fixed_payment_amount": 5000,
        "liability_payment_policy": "fixed", "liability_closing_day": 25,
    })

    def snapshot():
        return [dict(row) for row in db.execute(sa.select(models.Account.__table__).order_by(models.Account.id)).mappings()]

    assert "balance" not in models.Account.__table__.columns
    before = snapshot()
    writes = []

    def capture(_connection, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("UPDATE ACCOUNTS", "INSERT INTO ACCOUNTS", "DELETE FROM ACCOUNTS")):
            writes.append(statement)

    with _capture(db.bind, capture):
        tx = _post(db, source, target, 1200)
        assert snapshot() == before
        from app import schemas
        ledger.update_transaction(db, tx.id, schemas.TransactionUpdate(amount=900), 1)
        assert snapshot() == before
        ledger.delete_transaction(db, tx)
        db.commit()
        assert snapshot() == before
    assert not writes
    print(f"All {len(before[0])} columns in all accounts unchanged after posting, editing and deleting; no account DML")


def test_export_omits_balance_and_a_v8_cache_still_imports(db):
    wallet, income = _account(db, "wallet"), _account(db, "income", "income")
    _post(db, income, wallet, 112419, "EUR")
    _post(db, income, wallet, 23248, "USD")
    document = export_client(db, db.get(models.Client, 1))
    # R3 took the format to 13; what this test is about is that the balance
    # column is absent and that a v8 document carrying one is ignored.
    assert document["version"] == 27
    assert all("balance" not in row for row in document["data"]["accounts"])
    data = document["data"]
    for row in data["accounts"]:
        row["balance"] = 999999.25
    manifest = build_manifest(1, data, document["exported_at"], None)
    manifest["export_version"] = 8
    target = models.Client(id=2, name="legacy target", general_settings={"currency": "JPY"})
    db.add(target)
    db.commit()
    import_client(db, target, data=data, version=8, manifest=manifest)
    imported = db.query(models.Account).filter_by(client_id=2, name="wallet").one()
    result = calculate_account_balances(db, [imported])[imported.id]
    assert result.balances_minor == {"EUR": 112419, "USD": 23248}
    assert result.balance == 0.0  # Missing rates cannot change exact holdings.
    print("export omits balance; v8 with stale balance imports journal holdings and ignores cache")


@pytest.mark.parametrize("currency", ["JPY", "USD"])
def test_settings_hybrids_crud_and_binder(db, currency):
    db.get(models.Client, 1).general_settings = {"currency": currency}
    db.commit()
    values = dict(zip(SETTINGS, [1200.0, 10.25 if currency == "USD" else 10.0, 50.0]))
    account = ledger.create_account(db, 1, {"name": "settings", "account_type": "liability", **values})
    alias = aliased(models.Account)
    for name, major in values.items():
        assert isinstance(models.Account.__table__.c[f"{name}_minor"].type, MinorUnits)
        assert getattr(account, f"{name}_minor") == Money.from_major(str(major), currency).minor
        assert getattr(account, name) == major
        assert db.query(getattr(alias, name)).filter(alias.id == account.id).scalar() == major
        with pytest.raises(AttributeError):
            setattr(account, name, major)
        with pytest.raises(sa.exc.StatementError, match="plain integer"):
            db.execute(sa.update(models.Account).where(models.Account.id == -1).values({f"{name}_minor": 1.25}))
    ledger.update_account(db, 1, account.id, {name: None for name in SETTINGS})
    assert all(getattr(account, f"{name}_minor") is None for name in SETTINGS)


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261012_0053_account_journal_balances.py"
    spec = importlib.util.spec_from_file_location("b5_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_SETTINGS = ("role_target_amount", *SETTINGS)


def _old_database():
    metadata = sa.MetaData()
    clients = sa.Table("clients", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("general_settings", sa.JSON))
    accounts = sa.Table("accounts", metadata, sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("client_id", sa.Integer), sa.Column("account_type", sa.String),
                        sa.Column("balance", sa.Float), *(sa.Column(name, sa.Float) for name in LEGACY_SETTINGS))
    txs = sa.Table("transactions", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("currency", sa.String))
    entries = sa.Table("journal_entries", metadata, sa.Column("id", sa.Integer, primary_key=True),
                       sa.Column("account_id", sa.Integer), sa.Column("transaction_id", sa.Integer),
                       sa.Column("debit_minor", sa.BigInteger), sa.Column("credit_minor", sa.BigInteger))
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(clients.insert(), [{"id": 1, "general_settings": {"currency": "JPY"}},
                                               {"id": 2, "general_settings": {"currency": "USD"}}])
        connection.execute(accounts.insert(), [
            {"id": 1, "client_id": 1, "account_type": "asset", "balance": 9999, **dict.fromkeys(LEGACY_SETTINGS, 1200.0)},
            {"id": 2, "client_id": 1, "account_type": "liability", "balance": 9999, **dict.fromkeys(LEGACY_SETTINGS, None)},
            {"id": 3, "client_id": 2, "account_type": "asset", "balance": 9999, **dict.fromkeys(LEGACY_SETTINGS, 12.34)},
        ])
        connection.execute(txs.insert(), [{"id": 1, "currency": "JPY"}, {"id": 2, "currency": "JPY"},
                                         {"id": 3, "currency": "EUR"}, {"id": 4, "currency": "USD"}])
        connection.execute(entries.insert(), [
            {"id": 1, "transaction_id": 1, "account_id": 1, "debit_minor": 1000, "credit_minor": 0},
            {"id": 2, "transaction_id": 1, "account_id": 2, "debit_minor": 0, "credit_minor": 1000},
            {"id": 3, "transaction_id": 2, "account_id": 1, "debit_minor": 0, "credit_minor": 250},
            {"id": 4, "transaction_id": 2, "account_id": 2, "debit_minor": 250, "credit_minor": 0},
            {"id": 5, "transaction_id": 3, "account_id": 3, "debit_minor": 112419, "credit_minor": 0},
            {"id": 6, "transaction_id": 3, "account_id": 2, "debit_minor": 0, "credit_minor": 112419},
            {"id": 7, "transaction_id": 4, "account_id": 3, "debit_minor": 23248, "credit_minor": 0},
            {"id": 8, "transaction_id": 4, "account_id": 2, "debit_minor": 0, "credit_minor": 23248},
        ])
    return engine


def _run(engine, direction):
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN")
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_migration(), direction)()


def test_migration_applied_reversed_and_recomputed(caplog):
    engine = _old_database()
    _run(engine, "upgrade")
    columns = {col["name"]: col for col in sa.inspect(engine).get_columns("accounts")}
    assert "balance" not in columns
    assert all(name not in columns for name in LEGACY_SETTINGS)
    assert all(isinstance(columns[f"{name}_minor"]["type"], sa.BigInteger) for name in LEGACY_SETTINGS)
    with engine.connect() as connection:
        rows = list(connection.execute(sa.text("SELECT * FROM accounts ORDER BY id")).mappings())
    for name in LEGACY_SETTINGS:
        assert [row[f"{name}_minor"] for row in rows] == [1200, None, 1234]
    # A downgrade must derive the current journal, not resurrect the pre-upgrade cache.
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE journal_entries SET debit_minor=1100 WHERE id=1"))
        connection.execute(sa.text("UPDATE journal_entries SET credit_minor=1100 WHERE id=2"))
    with caplog.at_level("WARNING", logger="alembic.runtime.migration"):
        _run(engine, "downgrade")
    assert "not meaningful holdings or FX valuation" in caplog.text
    assert "balance" in {col["name"] for col in sa.inspect(engine).get_columns("accounts")}
    with engine.connect() as connection:
        rows = list(connection.execute(sa.text("SELECT * FROM accounts ORDER BY id")).mappings())
    assert rows[0]["balance"] == 850.0
    assert rows[1]["balance"] == pytest.approx(850 + 1124.19 + 232.48)
    assert rows[2]["balance"] == pytest.approx(1124.19 + 232.48)
    for name in LEGACY_SETTINGS:
        assert [row[name] for row in rows] == [1200.0, None, 12.34]
        assert f"{name}_minor" not in rows[0]
    print("Upgrade: settings JPY 1200 -> 1200, USD 12.34 -> 1234, NULL preserved; balance dropped")
    print("Downgrade: settings restored; stale cache 9999 -> current journal 850; mixed scalar warned")
    engine.dispose()


@pytest.mark.parametrize("damage,message", [("fraction", "Lossy conversion"), ("currency", "supported currency"), ("overflow", "overflow")])
def test_migration_refuses_loss_and_unknown_currency(damage, message):
    engine = _old_database()
    with engine.begin() as connection:
        if damage == "currency":
            connection.execute(sa.text("UPDATE clients SET general_settings='{}' WHERE id=1"))
        else:
            connection.execute(sa.text("UPDATE accounts SET role_target_amount=:amount WHERE id=1"),
                               {"amount": 1.25 if damage == "fraction" else float(2 ** 63)})
    with pytest.raises(ValueError, match=message):
        _run(engine, "upgrade")
    assert "balance" in {col["name"] for col in sa.inspect(engine).get_columns("accounts")}
    assert "role_target_amount_minor" not in {col["name"] for col in sa.inspect(engine).get_columns("accounts")}
    engine.dispose()


def test_migration_unset_currency_all_null_succeeds_but_any_value_rolls_back():
    engine = _old_database()
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO clients (id, general_settings) VALUES (3, '{}')"))
        connection.execute(sa.text("INSERT INTO accounts (id, client_id, account_type) VALUES (4, 3, 'asset')"))

    def snapshot():
        columns = [col["name"] for col in sa.inspect(engine).get_columns("accounts")]
        with engine.connect() as connection:
            rows = list(connection.execute(sa.text("SELECT * FROM accounts ORDER BY id")).mappings())
        return columns, [dict(row) for row in rows]

    _run(engine, "upgrade")
    assert all(snapshot()[1][-1][f"{name}_minor"] is None for name in LEGACY_SETTINGS)
    _run(engine, "downgrade")
    assert all(snapshot()[1][-1][name] is None for name in LEGACY_SETTINGS)

    # Zero is still money: each setting alone must require a denomination.
    for direction, suffix in (("upgrade", ""), ("downgrade", "_minor")):
        if direction == "downgrade":
            _run(engine, "upgrade")
        for name in LEGACY_SETTINGS:
            column = f"{name}{suffix}"
            with engine.begin() as connection:
                connection.execute(sa.text(f"UPDATE accounts SET {column} = 0 WHERE id = 4"))
            before = snapshot()
            with pytest.raises(ValueError, match=r"^Cannot resolve supported currency in accounts, row 4: None$"):
                _run(engine, direction)
            assert snapshot() == before
            with engine.begin() as connection:
                connection.execute(sa.text(f"UPDATE accounts SET {column} = NULL WHERE id = 4"))
    _run(engine, "downgrade")
    assert all(snapshot()[1][-1][name] is None for name in LEGACY_SETTINGS)
    engine.dispose()
