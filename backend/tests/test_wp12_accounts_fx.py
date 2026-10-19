"""WP12 data moves and tracking use test fixtures and mocked market data only."""
from datetime import date
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import models
from app.database import get_db
from app.dependencies import get_current_client
from app.domain.errors import DomainError, Invalid, detail_for, status_for
from app.domain.transfer import EXPORT_VERSION, build_manifest, validate_import_payload
from app.routers.exchange_rates import router
from app.services import fx_service as fx, life_scenario_service as scenarios
from app.services.account_return_service import blended_return
from app.services.data_transfer_service import export_client, import_client
from app.services.ledger_service import create_account
from app.workflows import fx_workflow
from test_life_scenarios import db, request, account


@pytest.fixture
def market(monkeypatch):
    calls = []
    def fetch(base, quote):
        calls.append((base, quote))
        return {"rate": 150.5, "market_date": "2026-10-16", "provider": "frankfurter"}
    monkeypatch.setattr(fx, "fetch_frankfurter_rate", fetch)
    return calls


@pytest.fixture
def api(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)
    @app.exception_handler(DomainError)
    async def error(_, exc):
        return JSONResponse(status_code=status_for(exc), content={"detail": detail_for(exc)})
    return app


def test_tracking_fetches_immediately_uses_market_date_and_is_client_scoped(db, market):
    tracked = fx_workflow.track(db, 1, "usd")
    assert (tracked.client_id, tracked.currency) == (1, "USD")
    rate = fx.list_rates(db, 1)[0]
    assert (rate.rate, rate.as_of_date, rate.source) == (150.5, date(2026, 10, 16), "frankfurter")
    assert market == [("USD", "JPY")]
    assert fx.list_tracked(db, 2) == fx.list_rates(db, 2) == []
    assert fx_workflow.track(db, 2, "USD").currency == "USD"


@pytest.mark.parametrize("code", ["JPY", "GBP", "XXX", "US", "123"])
def test_invalid_tracking_never_writes(db, market, code):
    with pytest.raises(Invalid):
        fx_workflow.track(db, 1, code)
    assert fx.list_tracked(db, 1) == fx.list_rates(db, 1) == []
    assert market == []


@pytest.mark.parametrize("failure", ["network", "missing", "negative", "nan", "infinite", "date"])
def test_unpriceable_currency_is_rejected_atomically(db, monkeypatch, failure):
    def fetch(*_):
        if failure == "network":
            raise RuntimeError("offline")
        return {"rate": {"negative": -1, "nan": float("nan"), "infinite": float("inf")}.get(failure, 1),
                "market_date": "bad" if failure == "date" else "2026-10-16", "provider": "frankfurter"} if failure != "missing" else {}
    monkeypatch.setattr(fx, "fetch_frankfurter_rate", fetch)
    with pytest.raises(Invalid):
        fx_workflow.track(db, 1, "USD")
    assert fx.list_tracked(db, 1) == fx.list_rates(db, 1) == []


def test_duplicate_tracking_preserves_original_rate_and_unique_constraint(db, market):
    fx_workflow.track(db, 1, "USD")
    before = [(row.id, row.rate) for row in fx.list_rates(db, 1)]
    with pytest.raises(Invalid):
        fx_workflow.track(db, 1, "USD")
    assert len(fx.list_tracked(db, 1)) == 1
    assert [(row.id, row.rate) for row in fx.list_rates(db, 1)] == before


def test_refresh_fetches_every_tracked_currency_again_and_not_other_currencies(db, market, monkeypatch, caplog):
    fx_workflow.track(db, 1, "USD")
    fx_workflow.track(db, 1, "EUR")
    fx_workflow.track(db, 2, "EUR")
    market.clear()
    def fetch(base, quote):
        market.append((base, quote))
        if base == "EUR":
            raise RuntimeError("EUR offline")
        return {"rate": 151, "market_date": "2026-10-16", "provider": "frankfurter"}
    monkeypatch.setattr(fx, "fetch_frankfurter_rate", fetch)
    result = fx_workflow.refresh(db, 1)
    assert market == [("EUR", "JPY"), ("USD", "JPY")]
    assert len(result["updated"]) == len(result["errors"]) == 1
    assert fx.list_rates(db, 1, "USD")[0].rate == 151
    assert fx.list_rates(db, 2)[0].rate == 150.5
    assert "FX refresh failed: client=1 currency=EUR" in caplog.text


def test_untracking_keeps_rates_and_refresh_does_not_retrack(db, market):
    fx_workflow.track(db, 1, "USD")
    rate_id = fx.list_rates(db, 1)[0].id
    fx_workflow.untrack(db, 1, "USD")
    market.clear()
    assert fx.list_tracked(db, 1) == []
    assert fx.list_rates(db, 1)[0].id == rate_id
    assert fx_workflow.refresh(db, 1)["updated"] == []
    assert market == []
    fx_workflow.delete_rate(db, 1, rate_id)
    assert fx.list_rates(db, 1) == []


def test_daily_refresh_continues_to_next_client_after_failure(db, market, monkeypatch, caplog):
    fx_workflow.track(db, 1, "USD")
    fx_workflow.track(db, 2, "EUR")
    visited = []
    def refresh(_, client_id):
        visited.append(client_id)
        if client_id == 1:
            raise RuntimeError("client failure")
    monkeypatch.setattr(fx_workflow, "refresh", refresh)
    fx_workflow.refresh_all(db)
    assert visited == [1, 2]
    assert "client=1" in caplog.text


def test_http_tracking_crud_refresh_and_removed_manual_endpoints(db, api, market):
    response = request(api, "POST", "/exchange-rates/tracked", json={"currency": "USD"})
    assert response.status_code == 200 and response.json()["currency"] == "USD"
    assert request(api, "POST", "/exchange-rates/tracked", json={"currency": "EUR", "rate": 9}).status_code == 422
    assert request(api, "GET", "/exchange-rates/tracked").json()[0]["currency"] == "USD"
    assert request(api, "POST", "/exchange-rates/auto-update").status_code == 200
    assert request(api, "POST", "/exchange-rates/", json={}).status_code == 405
    rate = request(api, "GET", "/exchange-rates/").json()[0]
    assert request(api, "PUT", f'/exchange-rates/{rate["id"]}', json={"rate": 1}).status_code == 405
    assert request(api, "DELETE", "/exchange-rates/tracked/USD").status_code == 200
    assert request(api, "GET", "/exchange-rates/").json()[0]["id"] == rate["id"]
    assert request(api, "DELETE", f'/exchange-rates/{rate["id"]}').status_code == 200


def test_scenario_override_zero_and_fallback_use_no_account_or_institution_assumption(db):
    holding = account(db, balance=10000)
    assert blended_return(db, 1, gross_annual_return=8, tax_rate=25) == 6
    assert blended_return(db, 1, gross_annual_return=8, tax_rate=25, account_returns={holding.id: 0}) == 0
    assert blended_return(db, 1, gross_annual_return=8, tax_rate=25, account_returns={holding.id: 4}) == 3


def test_backup_moves_old_yields_into_every_scenario_preserving_override(db):
    holding = account(db)
    none = account(db, name="未設定")
    zero = account(db, name="ゼロ")
    first = scenarios.create(db, 1, "一")
    second = scenarios.create(db, 1, "二")
    scenarios.replace_account_returns(db, 1, first.id, [{"account_id": holding.id, "annual_return": 9}])
    document = export_client(db, db.get(models.Client, 1))
    for row in document["data"]["accounts"]:
        row.update(role="growth", parent_id=9999, institution="removed", withdrawable_from_age=-5,
                   expected_return=3.5 if row["id"] == holding.id else (0 if row["id"] == zero.id else None))
    document["data"]["exchange_rates"] = [{"id": 1, "base_currency": "JPY", "quote_currency": "USD", "rate": .007, "as_of_date": "2026-10-16"}]
    document["data"].pop("fx_tracked_currencies")
    manifest = build_manifest(1, document["data"], "2026-10-19", None)
    manifest["export_version"] = 22
    assert validate_import_payload(document["data"], 22, manifest)["error_count"] == 0
    import_client(db, db.get(models.Client, 2), data=document["data"], version=22, manifest=manifest)
    restored = export_client(db, db.get(models.Client, 2))
    assert restored["version"] == EXPORT_VERSION == 23
    names = {row["id"]: row["name"] for row in restored["data"]["accounts"]}
    story_names = {row["id"]: row["name"] for row in restored["data"]["life_scenarios"]}
    assert {(story_names[row["scenario_id"]], names[row["account_id"]]): row["annual_return"] for row in restored["data"]["life_scenario_account_returns"]} == {
        ("一", holding.name): 9, ("二", holding.name): 3.5, ("一", zero.name): 0, ("二", zero.name): 0,
    }
    assert restored["data"]["fx_tracked_currencies"][0]["currency"] == "USD"
    assert all(not {"role", "parent_id", "expected_return", "institution"} & row.keys() for row in restored["data"]["accounts"])


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261019_0075_accounts_fx.py"
    spec = importlib.util.spec_from_file_location("wp12_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("method", ["upgrade", "roundtrip"])
def test_migration_preserves_yields_rates_and_seeds_distinct_nonbase_currencies(method):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        statements = [
            "CREATE TABLE clients (id INTEGER PRIMARY KEY, general_settings JSON)",
            """CREATE TABLE accounts (id INTEGER PRIMARY KEY, client_id INTEGER REFERENCES clients(id), name VARCHAR, account_type VARCHAR,
                role VARCHAR, role_target_amount_minor BIGINT, institution VARCHAR, withdrawable_from_age INTEGER,
                parent_id INTEGER REFERENCES accounts(id), expected_return FLOAT,
                CONSTRAINT ck_accounts_institution CHECK (institution IN ('none', 'ideco')),
                CONSTRAINT ck_accounts_withdrawable_from_age CHECK (withdrawable_from_age IS NULL OR withdrawable_from_age >= 0))""",
            "CREATE TABLE life_scenarios (id INTEGER PRIMARY KEY, client_id INTEGER)",
            "CREATE TABLE life_scenario_account_returns (id INTEGER PRIMARY KEY, scenario_id INTEGER, account_id INTEGER, annual_return FLOAT, UNIQUE(scenario_id, account_id))",
            "CREATE TABLE exchange_rates (id INTEGER PRIMARY KEY, client_id INTEGER, base_currency VARCHAR, quote_currency VARCHAR, rate FLOAT)",
            "INSERT INTO clients VALUES (1, '{\"currency\":\"JPY\"}'), (2, '{\"currency\":\"USD\"}')",
            "INSERT INTO accounts (id, client_id, name, account_type, expected_return) VALUES (1,1,'yield','asset',3.5), (2,1,'null','asset',NULL), (3,1,'zero','asset',0), (4,2,'other','asset',8), (5,1,'income','income',99)",
            "INSERT INTO life_scenarios VALUES (1,1), (2,1), (3,2)",
            "INSERT INTO life_scenario_account_returns (scenario_id,account_id,annual_return) VALUES (1,1,9)",
            "INSERT INTO exchange_rates VALUES (1,1,'USD','JPY',150), (2,1,'JPY','USD',.007), (3,1,'EUR','USD',1.1), (4,2,'USD','JPY',150)",
        ]
        for statement in statements:
            connection.exec_driver_sql(statement)
        rates = connection.exec_driver_sql("SELECT * FROM exchange_rates").all()
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        assert connection.exec_driver_sql("SELECT scenario_id,account_id,annual_return FROM life_scenario_account_returns ORDER BY scenario_id,account_id").all() == [(1,1,9), (1,3,0), (2,1,3.5), (2,3,0), (3,4,8)]
        assert connection.exec_driver_sql("SELECT client_id,currency FROM fx_tracked_currencies ORDER BY client_id,currency").all() == [(1,'EUR'), (1,'USD'), (2,'JPY')]
        assert connection.exec_driver_sql("SELECT * FROM exchange_rates").all() == rates
        assert not {"role", "role_target_amount_minor", "institution", "withdrawable_from_age", "parent_id", "expected_return"} & {col["name"] for col in sa.inspect(connection).get_columns("accounts")}
        if method == "roundtrip":
            with Operations.context(MigrationContext.configure(connection)):
                migration().downgrade()
                migration().upgrade()
            assert connection.exec_driver_sql("SELECT count(*) FROM life_scenario_account_returns").scalar() == 5
    engine.dispose()


def test_daily_loop_runs_fx_even_if_recording_fails(monkeypatch):
    import asyncio
    from unittest.mock import Mock
    import importlib
    from app import main
    # Other suites also import backend.app; patch the loop's actual package.
    package = main.run_automatic_recording_loop.__module__.rsplit(".", 1)[0]
    database = importlib.import_module(f"{package}.database")
    automatic_recording_workflow = importlib.import_module(f"{package}.workflows.automatic_recording_workflow")
    loop_fx = importlib.import_module(f"{package}.workflows.fx_workflow")
    session = Mock()
    visited = []
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    def broken(*_, **__):
        raise RuntimeError("recording failed")
    monkeypatch.setattr(automatic_recording_workflow, "process_due_all", broken)
    monkeypatch.setattr(loop_fx, "refresh_all", lambda db: visited.append(db))
    async def stop(_):
        raise asyncio.CancelledError
    monkeypatch.setattr(main.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main.run_automatic_recording_loop())
    assert visited == [session]
    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_tracking_prices_against_the_clients_base_currency(db, market):
    db.get(models.Client, 2).general_settings = {"currency": "USD"}
    db.commit()
    fx_workflow.track(db, 2, "EUR")
    assert market == [("EUR", "USD")]
    assert fx.list_rates(db, 2)[0].quote_currency == "USD"
    with pytest.raises(Invalid):
        fx_workflow.track(db, 2, "USD")


def test_tracking_current_format_roundtrip_preserves_untracked_history(db, market):
    fx_workflow.track(db, 1, "EUR")
    fx_workflow.track(db, 1, "USD")
    fx_workflow.untrack(db, 1, "USD")
    source = export_client(db, db.get(models.Client, 1))
    import_client(db, db.get(models.Client, 2), data=source["data"], version=source["version"], manifest=source["manifest"])
    assert [row.currency for row in fx.list_tracked(db, 2)] == ["EUR"]
    assert {row.base_currency for row in fx.list_rates(db, 2)} == {"EUR", "USD"}


def test_four_account_kinds_and_removed_fields_are_rejected_through_http_schemas(db):
    from pydantic import ValidationError
    from app.routers.accounts import AccountCreate, AccountUpdate
    for kind in ("asset", "liability", "income", "expense"):
        assert create_account(db, 1, {"name": kind, "account_type": kind}).account_type == kind
    for kind in ("item", "revenue", "equity", "unknown"):
        with pytest.raises(Invalid):
            create_account(db, 1, {"name": kind, "account_type": kind})
        with pytest.raises(ValidationError):
            AccountCreate(name=kind, account_type=kind)
    for field in ("role", "role_target_amount", "institution", "withdrawable_from_age", "parent_id", "expected_return"):
        with pytest.raises(ValidationError):
            AccountUpdate(**{field: None})


def test_migration_refuses_unexpected_item_accounts_before_changing_data():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_type VARCHAR)")
        connection.exec_driver_sql("INSERT INTO accounts VALUES (1, 'item')")
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="item"):
                migration().upgrade()
        assert sa.inspect(connection).get_table_names() == ["accounts"]
        assert connection.exec_driver_sql("SELECT * FROM accounts").all() == [(1, "item")]
    engine.dispose()
