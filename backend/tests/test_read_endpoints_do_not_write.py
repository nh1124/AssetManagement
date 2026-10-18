"""A GET endpoint must not cause a database write.

Full persisted rows are compared across real HTTP requests, including auth and
response serialization. Fixture paths a GET does not reach can still hide writes.
A POST that only reads is not an error. Writes in background tasks outside the
request are not observed; startup jobs are deliberately not run against this DB.
"""
from __future__ import annotations

from app.services.money_storage import to_minor, rule_amount_fields


from backend.app.domain.money import Money

from dataclasses import dataclass
from datetime import date, timedelta
import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.main import app
from app.services.cache_service import invalidate_client
from app.services.fx_service import get_client_currency
from app.services.ledger_service import ensure_default_accounts, create_transaction
from app.utils.jwt import create_access_token


ALLOWED: dict[str, str] = {}


# Writes a read is supposed to make. These are not a backlog: the stale-entry
# test still requires each to write, so one that stops writing has to be moved
# or removed deliberately, but no wave is expected to empty this list.
BY_DESIGN: dict[str, str] = {
    "GET /ai/context/summary": (
        "Writes ai_audit_logs. Recording what an AI read is the purpose of the "
        "endpoint, not a side effect of it; docs/specs/ai_data_access_catalog.md. "
        "The former budget-plan write is gone."
    ),
    "GET /ai/context/resource/{resource}": (
        "Writes ai_audit_logs. Recording what an AI read is the purpose of the "
        "endpoint, not a side effect of it; docs/specs/ai_data_access_catalog.md. "
        "The former budget-plan write is gone."
    ),
    "GET /ai/context/resources": (
        "Writes ai_audit_logs. Recording what an AI read is the purpose of the "
        "endpoint, not a side effect of it; docs/specs/ai_data_access_catalog.md."
    ),
}

# An undrivable endpoint belongs here with a concrete reason, never as a passing
# request that returned an auth/validation error. The existence check is the
# minimum ratchet; it cannot prove an external/MFA fixture remains impossible.
UNDRIVABLE_GETS: dict[str, str] = {}


def _get_routes():
    routes = []
    for route in app.routes:
        # FastAPI can retain included routers as lazy branches; ignoring those
        # would silently lose every feature router on newer installations.
        candidates = (
            route.effective_route_contexts()
            if hasattr(route, "effective_route_contexts") else [route]
        )
        routes.extend(r for r in candidates if "GET" in (r.methods or set()))
    keys = [f"GET {r.path}" for r in routes]
    assert len(keys) == len(set(keys)), "Duplicate GET paths need separate request cases"
    return sorted(routes, key=lambda r: r.path)


def _seed(db, scenario, today):
    db.add(models.Client(id=1, name="GET guard", username="get-guard", general_settings={"currency": "JPY"}))
    db.flush()
    if scenario != "missing_default_accounts":
        ensure_default_accounts(db, 1)
    cash = models.Account(client_id=1, name="Guard cash", account_type="asset", role="operating")
    expense = models.Account(client_id=1, name="Guard food", account_type="expense")
    income = models.Account(client_id=1, name="Guard salary", account_type="revenue")
    db.add_all([cash, expense, income])
    db.flush()
    currency = get_client_currency(db, 1)
    create_transaction(db, client_id=1, date=today, amount_minor=Money.from_major(str(100000), currency).minor, currency=currency,
                       description="Salary", from_account_id=income.id, to_account_id=cash.id)
    lunch = create_transaction(db, client_id=1, date=today, amount_minor=Money.from_major(str(1200), currency).minor, currency=currency,
                               description="Lunch", from_account_id=cash.id, to_account_id=expense.id)
    batch = models.TransactionBatch(client_id=1, label="Guard batch")
    db.add(batch)
    db.flush()
    lunch.batch_id = batch.id
    # Drive saved scenario reads with real assumptions, without granting a GET exception.
    life_scenario = models.LifeScenario(
        client_id=1, name="Guard life scenario", is_goal=True,
        account_returns=[models.LifeScenarioAccountReturn(account_id=cash.id, annual_return=3.0)],
    )
    alternate_scenario = models.LifeScenario(client_id=1, name="Guard alternate", annual_return=7.0)
    db.add_all([life_scenario, alternate_scenario])
    db.flush()
    goal = models.LifeEvent(scenario_id=life_scenario.id, client_id=1, name="Guard goal", start_date=today,
                            target_date=today + timedelta(days=365), target_amount_minor=to_minor(200000, "JPY"),
                            priority=1)
    db.add(goal)
    db.flush()
    capsule = models.Capsule(client_id=1, life_event_id=goal.id, name="Guard capsule",
                             target_amount_minor=to_minor(200000, "JPY"), monthly_contribution_minor=to_minor(10000, "JPY"),
                             funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=cash.id, target_amount_minor=to_minor(200000, "JPY"))])
    db.add(capsule)
    db.flush()
    credit = db.query(models.JournalEntry).filter_by(transaction_id=lunch.id, account_id=cash.id).one()
    credit.capsule_id = capsule.id
    db.add(models.CapsuleDrawdown(client_id=1, capsule_id=capsule.id,
                                 transaction_id=lunch.id, kind="as_intended", amount_minor=1200))
    product = models.Product(client_id=1, name="Guard supplies", category="Guard food",
                             last_unit_price_minor=to_minor(1000, "JPY"), frequency_days=30, units_per_purchase=1,
                             last_purchase_date=today, budget_account_id=expense.id,
                             budget_treatment="expense_only")
    registry = models.RegistryEntry(client_id=1, name="Guard subscription", amount_minor=to_minor(1000, "JPY"),
                                    budget_account_id=expense.id, source_account_id=cash.id,
                                    generate_recurring=True)
    db.add_all([product, registry])
    db.flush()
    plan = None
    if scenario == "existing_plan":
        plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        db.add(plan)
        db.flush()
    start = today.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    db.add_all([
        models.Product(client_id=1, name="Guard equipment", category="Equipment",
                       last_unit_price_minor=to_minor(12000, "JPY"), purchase_price_minor=to_minor(12000, "JPY"),
                       purchase_date=today - timedelta(days=30), is_asset=True,
                       lifespan_months=12, budget_treatment="asset_replacement"),
        # An orphan plan line exposes writes that a normalised fixture would conceal.
        models.MonthlyPlanLine(client_id=1, plan_id=plan.id if plan else None,
                               target_period=today.strftime("%Y-%m"), line_type="expense",
                               name="Guard food", amount_minor=to_minor(3000, "JPY"), account_id=expense.id,
                               source_account_id=cash.id),
        models.RecurringTransaction(client_id=1, name=registry.name, amount_minor=to_minor(1000, "JPY"),
                                    frequency="Monthly", day_of_month=today.day,
                                    from_account_id=cash.id, to_account_id=expense.id,
                                    next_due_date=today, source_registry_entry_id=registry.id),
        models.CapsuleRule(client_id=1, capsule_id=capsule.id, trigger_type="Income",
                           amount_type="fixed", **rule_amount_fields(100, "fixed", "JPY")),
        models.Milestone(client_id=1, life_event_id=goal.id, date=goal.target_date,
                         target_amount_minor=to_minor(200000, "JPY")),
        models.SimulationConfig(client_id=1),
        models.SimulationScenario(client_id=1, life_event_id=goal.id, name="Guard scenario",
                                  annual_return=5, inflation=2, monthly_savings_minor=to_minor(10000, "JPY")),
        models.PeriodReview(client_id=1, start_date=start, end_date=end, label="Guard review"),
        models.MonthlyAction(client_id=1, source_period=today.strftime("%Y-%m"),
                             proposal_id="guard", kind="review", idempotency_key="guard"),
        models.ExchangeRate(client_id=1, base_currency="USD", quote_currency="JPY",
                            rate=150, as_of_date=today),
        models.ClientMfaSetting(client_id=1, enabled=False),
        models.AiOperationPolicy(client_id=1, resource="ai_context", action="read",
                                 risk="low", mode="allow_read"),
        models.AiAuditLog(client_id=1, source="backend", resource="ai_context",
                          action="read", risk="low", decision="allowed"),
        models.AiChangeRequest(client_id=1, source="backend", resource="transactions",
                               action="create", risk="low", idempotency_key="guard"),
    ])
    member = models.HouseholdMember(client_id=1, name="子", birth_date=date(2010, 4, 1))
    db.add(member)
    db.flush()
    db.add_all([
        models.LifeEventCondition(client_id=1, life_event_id=goal.id, metric="member_age", comparator="gte", threshold_number=18, reference_id=member.id),
        models.LifeEventCondition(client_id=1, life_event_id=goal.id, metric="net_worth", comparator="gte", threshold_minor=1),
        models.LifeEventCondition(client_id=1, life_event_id=goal.id, metric="free_cash", comparator="gte", threshold_minor=1),
        models.LifeEventCondition(client_id=1, life_event_id=goal.id, metric="account_balance", comparator="gte", threshold_minor=1, reference_id=cash.id),
        models.LifeEventCondition(client_id=1, life_event_id=goal.id, metric="capsule_claim", comparator="gte", threshold_minor=1, reference_id=capsule.id),
        models.LifeEventCondition(client_id=1, life_event_id=goal.id, metric="goal_progress", comparator="gte", threshold_number=1, reference_id=goal.id),
        models.LifeEventCondition(client_id=1, life_event_id=goal.id, metric="date_reached", comparator="gte", threshold_date=today),
    ])
    db.commit()
    return {"batch_id": batch.id, "account_id": cash.id, "event_id": goal.id, "life_event_id": goal.id,
            # lunch is the trigger a capsule rule would fire on, so the
            # reservation read is driven against an entry that has legs.
            "capsule_id": capsule.id, "product_id": product.id, "transaction_id": lunch.id, "month": today.strftime("%Y-%m"), "period": today.strftime("%Y-%m"),
            "plan_ids": str(plan.id) if plan else None,
            "ids": f"{life_scenario.id},{alternate_scenario.id}",
            # Preview switching the goal to the other story, the case that reads the most.
            "scenario_id": alternate_scenario.id,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            # Statement reconciliation is a pure read, including its historical claims.
            "as_of": today.isoformat(), "statement": "98800",
            "start_period": today.strftime("%Y-%m")}


def _snapshot(engine):
    # Core reads bypass ORM identity caches. Serialising JSON also detaches
    # mutable values, and sorting keeps row order out of the comparison.
    with engine.connect() as connection:
        return {
            table.name: sorted(
                json.dumps(dict(row), sort_keys=True, default=str)
                for row in connection.execute(select(table)).mappings()
            )
            for table in Base.metadata.tables.values()
        }


# Both lists are exempt from the rule. ALLOWED is a backlog and should reach
# zero; BY_DESIGN never will. The stale-entry test holds both, so an endpoint
# that stops writing has to be removed from whichever list names it.
_EXEMPT = {**ALLOWED, **BY_DESIGN}


@dataclass
class Observation:
    endpoint: str
    case: str
    tables: dict[str, tuple[int, int]]
    error: str = ""


def _drive(route, scenario, resource, today):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    endpoint = f"GET {route.path}"
    case = scenario + (f"/{resource}" if resource else "")
    try:
        with sessions() as db:
            values = _seed(db, scenario, today)
        values["resource"] = resource
        path = route.path
        for name in route.param_convertors:
            assert name in values and values[name] is not None, f"{endpoint}: no fixture for {name}"
            path = path.replace("{" + name + "}", str(values[name]))
        params = {}
        dependant = getattr(route, "dependant", None)
        if dependant:
            for field in dependant.query_params:
                if field.name == "month":
                    params[field.alias] = today.month
                elif field.name in values and values[field.name] is not None:
                    params[field.alias] = values[field.name]
                elif field.field_info.is_required():
                    raise AssertionError(f"{endpoint}: no fixture for required query {field.name}")

        def override_db():
            with sessions() as db:
                yield db

        previous = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = override_db
        invalidate_client(1)
        try:
            before = _snapshot(engine)
            try:
                response = asyncio.run(_request(path, params))
                error = "" if response.status_code == 200 else f"HTTP {response.status_code}: {response.text[:300]}"
            except Exception as exc:
                # A failed request is coverage debt even if its tables did not
                # move. Keep scanning so one failure cannot hide later routes.
                error = f"{type(exc).__name__}: {exc}"
            after = _snapshot(engine)
            tables = {name: (len(before[name]), len(after[name])) for name in before
                      if before[name] != after[name]}
            return Observation(endpoint, case, tables, error)
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous)
            invalidate_client(1)
    finally:
        engine.dispose()


async def _request(path, params):
    # ASGITransport does not run lifespan: migrations and the recurring worker
    # must never touch real data while a test owns only an in-memory database.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as http:
        request = asyncio.create_task(http.get(
            path, params=params, follow_redirects=False,
            headers={"Authorization": "Bearer " + create_access_token("1", "get-guard")},
        ))
        # The sandbox can lose selector wakeups from the sync endpoint worker.
        # A timer keeps completions visible without replacing endpoint code.
        deadline = asyncio.get_running_loop().time() + 30
        while not request.done():
            await asyncio.wait({request}, timeout=0.01)
            if asyncio.get_running_loop().time() >= deadline:
                request.cancel()
                raise AssertionError(f"GET {path}: request did not complete in 30 seconds")
        return request.result()


@pytest.fixture(scope="module")
def read_scan():
    routes = _get_routes()
    observations = []
    today = date.today()
    for route in routes:
        if f"GET {route.path}" in UNDRIVABLE_GETS:
            continue
        scenarios = ("existing_plan",) if route.path == "/budget-plans/compare" else (
            "existing_plan", "no_plan", "missing_default_accounts",
        )
        # Different resources share one route but dispatch into different
        # services. Summary must not disappear behind an accounts-only case.
        resources = ("summary", "accounts", "transactions_recent", "monthly_plan",
                     "recurring_transactions", "goals", "products", "registry_entries",
                     "settings", "audit_logs") if "{resource}" in route.path else (None,)
        for scenario in scenarios:
            for resource in resources:
                observations.append(_drive(route, scenario, resource, today))
    return {f"GET {route.path}" for route in routes}, observations


def test_get_endpoints_do_not_write(read_scan):
    _, observations = read_scan
    failures = [f"{o.endpoint} [{o.case}]: {o.error}" for o in observations if o.error]
    failures.extend(f"{o.endpoint} [{o.case}]: changed tables={o.tables}"
                    for o in observations if o.tables and o.endpoint not in _EXEMPT)
    assert not failures, "GET scan failures:\n" + "\n".join(failures)


def test_allowed_matches_observed_writes(read_scan):
    _, observations = read_scan
    observed = {o.endpoint for o in observations if o.tables}
    stale = sorted(set(_EXEMPT) - observed)
    missing = sorted(observed - set(_EXEMPT))
    assert not (stale or missing), (
        "The exempt lists do not match what was observed:\n"
        f"stale entries={stale}\nmissing entries={missing}"
    )


def test_undrivable_list_is_accurate(read_scan):
    endpoints, observations = read_scan
    assert all(reason.strip() for reason in UNDRIVABLE_GETS.values())
    assert not (set(UNDRIVABLE_GETS) - endpoints), "Skipped GET endpoint no longer exists"
    driven = {o.endpoint for o in observations if not o.error}
    assert driven | set(UNDRIVABLE_GETS) == endpoints, "GET endpoint was neither driven nor explicitly skipped"
    assert not (driven & set(UNDRIVABLE_GETS)), "Driven GET endpoint still on skip list"
