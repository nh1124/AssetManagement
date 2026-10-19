"""Reads report existing state; initialization belongs to write paths."""
from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.domain.journal import Leg
from app.database import Base, get_db
from app.main import app
from app.services.budget_context import BudgetContext
from app.services.budget_credit_settlement import (
    _build_credit_settlement_plan_lines,
    credit_settlement_plan_lines,
)
from app.services.budget_plan_store import find_budget_plan_id
from app.services.budget_projection import planned_cash_outflow_remaining
from app.services.cache_service import invalidate_client
from app.services.ledger_service import DEFAULT_ACCOUNTS, create_transaction
from app.utils.jwt import create_access_token


@pytest.fixture
def database():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        db.add(models.Client(id=1, name="Read test", username="read-test",
                             general_settings={"currency": "JPY"}))
        db.commit()

    def override_db():
        with sessions() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    invalidate_client(1)
    try:
        yield sessions
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        invalidate_client(1)
        engine.dispose()


def request(method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://testserver") as http:
            pending = asyncio.create_task(http.request(
                method, path, headers={"Authorization": "Bearer " +
                                      create_access_token("1", "read-test")}, **kwargs))
            # Keep selector wakeups visible for sync handlers in the sandbox.
            deadline = asyncio.get_running_loop().time() + 30
            while not pending.done():
                await asyncio.wait({pending}, timeout=0.01)
                if asyncio.get_running_loop().time() >= deadline:
                    pending.cancel()
                    raise AssertionError(f"{method} {path} did not complete")
            return pending.result()
    return asyncio.run(run())


@pytest.mark.parametrize("path,params", [
    ("/analysis/summary", {}),
    ("/analysis/balance-sheet", {}),
    ("/analysis/profit-loss", {}),
    ("/analysis/account-flows", {"start_date": "2026-01-01", "end_date": "2026-12-31"}),
    ("/analysis/net-position", {}),
])
def test_analysis_without_default_accounts(database, path, params):
    with database() as db:
        before = db.query(models.Account).count()
    assert before == 0
    response = request("GET", path, params=params)
    assert response.status_code == 200, response.text
    with database() as db:
        assert db.query(models.Account).count() == before


def test_registration_seeds_only_new_client(database):
    with database() as db:
        db.add(models.Account(client_id=1, name="Existing custom account", account_type="asset"))
        db.commit()
        before = db.execute(select(models.Account.__table__).where(
            models.Account.client_id == 1)).all()
    response = request("POST", "/auth/register", json={
        "username": "new-client", "password": "password123", "name": "New client"})
    assert response.status_code == 200, response.text
    client_id = response.json()["client_id"]
    assert client_id != 1
    with database() as db:
        accounts = db.query(models.Account).filter_by(client_id=client_id).all()
        assert len(accounts) == len(DEFAULT_ACCOUNTS) == 15
        assert {(a.name, a.account_type) for a in accounts} == {
            (a["name"], a["account_type"]) for a in DEFAULT_ACCOUNTS}
        assert db.execute(select(models.Account.__table__).where(
            models.Account.client_id == 1)).all() == before


def seed_actuals_and_orphan(db):
    cash = models.Account(client_id=1, name="cash", account_type="asset")
    salary = models.Account(client_id=1, name="Custom salary", account_type="income")
    food = models.Account(client_id=1, name="Custom food", account_type="expense")
    db.add_all([cash, salary, food])
    db.flush()
    create_transaction(db, client_id=1, date=date.today(), amount_minor=1000, currency="JPY",
                       description="Income", from_account_id=salary.id, to_account_id=cash.id)
    create_transaction(db, client_id=1, date=date.today(), amount_minor=100, currency="JPY",
                       description="Food", from_account_id=cash.id, to_account_id=food.id)
    orphan = models.MonthlyPlanLine(client_id=1, plan_id=None, target_period=date.today().strftime("%Y-%m"),
                                   line_type="expense", name=food.name, amount_minor=500,
                                   account_id=food.id, source_account_id=cash.id)
    # Virtual allocations and registry suggestions must not invent a plan either.
    db.add_all([orphan,
                models.Capsule(client_id=1, name="Reserve", monthly_contribution_minor=200),
                models.RegistryEntry(client_id=1, name='Subscription', amount_minor=300, budget_account_id=food.id, source_account_id=cash.id, start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly")])
    db.commit()
    return orphan.id


@pytest.mark.parametrize("path", [
    "/budget-plans", "/budget-plans/summary", "/budget-plans/lines",
    "/analysis/summary", "/analysis/variance", "/reports/monthly",
])
def test_reads_without_budget_plan_preserve_actuals(database, path):
    with database() as db:
        orphan_id = seed_actuals_and_orphan(db)
        assert db.query(models.BudgetPlan).count() == 0
        before = {table.name: db.execute(select(table)).all() for table in Base.metadata.tables.values()}
    response = request("GET", path)
    assert response.status_code == 200, response.text
    body = response.json()
    if path == "/budget-plans":
        assert body == []
    elif path in ("/budget-plans/summary", "/budget-plans/lines"):
        lines = body["plan_lines"] if path == "/budget-plans/summary" else body
        # WP11 counts the definition without creating a plan or adopting the orphan.
        assert len(lines) == 1
        assert lines[0]["id"] is None and lines[0]["source"] == "registry"
        assert lines[0]["amount"] == 0
        assert lines[0]["budget_amount"] == lines[0]["registry_amount"] == 300
        assert lines[0]["actual"] == 100
    if path == "/budget-plans/summary":
        assert body["plan_id"] is None
        for key in ("total_expected_inflow", "total_variable_budget", "total_allocation_plan", "total_debt_plan"):
            assert body[key] == 0
        assert len(body["cash_flow_projection"]) == len(body["balance_projection"]) == 12
        assert all(row["ending_cash"] == 900 and row["net_cash"] == 0 for row in body["cash_flow_projection"])
        assert all(row["total_assets"] == row["net_worth"] == 900 for row in body["balance_projection"])
    elif path == "/analysis/summary":
        assert body["monthly_pl"] == body["effective_cash"] == body["logical_balance"] == 900
        assert body["budget_usage_rate"] == 33.3
    elif path == "/analysis/variance":
        assert body["plan_id"] is None
        assert body["total_budget"] == 300
        assert body["total_actual"] == 100
        assert body["total_variance"] == 200
        assert next(item for item in body["items"] if item["category"] == "Custom food")["budget"] == 300
    elif path == "/reports/monthly":
        assert body["summary"]["monthly_pl"] == body["summary"]["net_worth"] == 900
        assert body["anomalies"] == []
    with database() as db:
        assert db.query(models.BudgetPlan).count() == 0
        assert db.get(models.MonthlyPlanLine, orphan_id).plan_id is None
        assert {table.name: db.execute(select(table)).all() for table in Base.metadata.tables.values()} == before


@pytest.mark.parametrize("case", ["defaults", "sorted", "none"])
def test_find_budget_plan_id_only_reads(database, case):
    with database() as db:
        expected = None
        if case != "none":
            plans = [models.BudgetPlan(client_id=1, name="First", sort_order=-5),
                     models.BudgetPlan(client_id=1, name="Second", sort_order=-5),
                     models.BudgetPlan(client_id=1, name="Default", sort_order=10,
                                       is_default=case == "defaults"),
                     models.BudgetPlan(client_id=1, name="Extra default", sort_order=20,
                                       is_default=case == "defaults")]
            db.add_all(plans)
            db.commit()
            expected = plans[2].id if case == "defaults" else plans[0].id
        db.add(models.MonthlyPlanLine(client_id=1, name="Orphan", target_period="2026-01",
                                     line_type="expense", amount_minor=100))
        db.commit()
        assert find_budget_plan_id(db, 1) == expected
        assert not db.new and not db.dirty and not db.deleted
        assert db.query(models.MonthlyPlanLine).one().plan_id is None
        if case != "none":
            assert find_budget_plan_id(db, 1, plans[1].id) == plans[1].id
            assert not db.new and not db.dirty and not db.deleted
            assert sum(p.is_default for p in plans) == (2 if case == "defaults" else 0)


def test_find_rejects_foreign_and_missing_plan(database):
    with database() as db:
        db.add(models.Client(id=2, name="Other"))
        db.add(models.BudgetPlan(client_id=2, name="Other plan"))
        db.commit()
        foreign_id = db.query(models.BudgetPlan).one().id
        assert find_budget_plan_id(db, 1) is None
        assert not db.new and not db.dirty and not db.deleted
        for plan_id in (foreign_id, 9999):
            with pytest.raises(ValueError, match="^Budget plan not found$"):
                find_budget_plan_id(db, 1, plan_id)
            assert not db.new and not db.dirty and not db.deleted


def test_plan_line_write_still_creates_plan(database):
    with database() as db:
        assert db.query(models.BudgetPlan).count() == 0
    response = request("POST", "/budget-plans/lines", json=[{
        "target_period": "2026-01", "line_type": "expense", "name": "Food", "amount": 100}])
    assert response.status_code == 200, response.text
    with database() as db:
        plan = db.query(models.BudgetPlan).one()
        line = db.get(models.MonthlyPlanLine, response.json()["ids"][0])
        assert line.plan_id == plan.id
        assert plan.is_default


def test_remaining_and_credit_lines_without_plan(database):
    with database() as db:
        seed_actuals_and_orphan(db)
        db.add(models.Account(client_id=1, name="Card", account_type="liability", liability_kind="card"))
        db.commit()
        ctx = BudgetContext(db, 1)
        period = date.today().strftime("%Y-%m")
        assert planned_cash_outflow_remaining(ctx, period) == 0
        assert credit_settlement_plan_lines(ctx, period) == []
        assert _build_credit_settlement_plan_lines(ctx, period) == []
        assert not db.new and not db.dirty and not db.deleted
        assert db.query(models.BudgetPlan).count() == 0


def test_credit_settlement_without_plan_keeps_posted_activity(database):
    with database() as db:
        orphan_id = seed_actuals_and_orphan(db)
        card = models.Account(client_id=1, name="Card", account_type="liability",
                              liability_kind="card", liability_payment_month_offset=0)
        db.add(card)
        db.flush()
        orphan = db.get(models.MonthlyPlanLine, orphan_id)
        orphan.source_account_id = card.id
        create_transaction(db, client_id=1, date=date.today(), amount_minor=400, currency="JPY",
                           description="Posted card charge", from_account_id=card.id,
                           to_account_id=orphan.account_id)
        db.commit()
        period = date.today().strftime("%Y-%m")
        lines = credit_settlement_plan_lines(BudgetContext(db, 1), period)
        assert len(lines) == 1
        assert lines[0]["suggested_amount"] == 400
        assert lines[0]["suggested_items"][0]["posted_amount"] == 400
        assert lines[0]["suggested_items"][0]["planned_remaining"] == 0
        assert db.query(models.BudgetPlan).count() == 0
        assert db.get(models.MonthlyPlanLine, orphan_id).plan_id is None
        assert not db.new and not db.dirty and not db.deleted


def test_capsule_list_reports_claim_without_retired_fields(database):
    with database() as db:
        cash = models.Account(client_id=1, name="Custom cash", account_type="asset")
        source = models.Account(client_id=1, name="Source", account_type="asset")
        capsule = models.Capsule(client_id=1, name="Reserve",
                                 target_amount_minor=1000, monthly_contribution_minor=0)
        db.add_all([cash, source, capsule])
        db.flush()
        create_transaction(db, client_id=1, date=date(2026, 10, 12), description="Attributed reserve",
                           amount_minor=250, currency="JPY",
                           legs=[Leg(cash.id, debit=250, capsule_id=capsule.id), Leg(source.id, credit=250)])
        db.commit()
        capsule_id = capsule.id
    response = request("GET", "/capsules/")
    assert response.status_code == 200, response.text
    assert response.json()[0]["current_balance"] == 250
    assert "holdings" not in response.json()[0]
    assert "account_id" not in response.json()[0]
