from app.services.money_storage import to_minor, minor_fields

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.routers import budget_plans as router
from backend.app.services import budget_plan_store as store


@pytest.fixture
def planning():
    engine = create_engine("sqlite:///:memory:")
    # Enforce the FK deletion rule as PostgreSQL does.
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    client = models.Client(id=1, name="planning")
    other = models.Client(id=2, name="other")
    db.add_all([client, other])
    db.commit()
    try:
        yield db, client
    finally:
        db.close()
        engine.dispose()


def _plan(db, *, client_id=1, name="Baseline", is_default=True, **values):
    plan = models.BudgetPlan(client_id=client_id, name=name, is_default=is_default, **values)
    db.add(plan)
    db.commit()
    return plan


def _line(db, plan, *, name="Food", period="2026-10", **values):
    line = models.MonthlyPlanLine(
        client_id=plan.client_id, plan_id=plan.id, name=name,
        target_period=period, line_type="expense", amount_minor=to_minor(100, "JPY"), **minor_fields(values, "JPY", 'amount'),
    )
    db.add(line)
    db.commit()
    return line


def test_the_plan_set_endpoints_are_gone():
    """§8-10: a client has one plan; listing, making, comparing and copying plans went with the old UI."""
    paths = {route.path for route in router.router.routes}
    assert paths == {"/budget-plans/copy-period", "/budget-plans/summary", "/budget-plans/lines",
                     "/budget-plans/lines/batch", "/budget-plans/lines/{line_id}",
                     "/budget-plans/product-reserves/preview", "/budget-plans/product-reserves/apply"}


def test_delete_single_plan_line_removes_only_that_line(planning):
    """X13: deleting one line deletes it, and frees its identity.

    is_active keeps its other two jobs -- the deduplication repair and
    copy-period replacement both use it to mark a line superseded -- so a
    line can still be set aside without being destroyed. That is simply no
    longer what DELETE does.
    """
    db, client = planning
    plan = _plan(db)
    deleted = _line(db, plan)
    deleted_id, identity = deleted.id, deleted.identity_key
    kept = _line(db, plan, name="Rent")
    assert store.delete_plan_line(db, client.id, deleted_id) is True
    db.expire_all()
    assert db.get(models.MonthlyPlanLine, deleted_id) is None
    assert db.query(models.MonthlyPlanLine).count() == 1
    assert kept.is_active is True
    assert (kept.plan_id, kept.amount) == (plan.id, 100)
    # The partial unique index covers active rows by identity; a deleted line
    # must not keep holding one.
    replacement = _line(db, plan)
    assert replacement.identity_key == identity
    assert store.delete_plan_line(db, client.id, deleted_id) is False


def test_line_delete_with_commit_false_is_rollbackable_by_caller(planning):
    db, client = planning
    plan = _plan(db)
    line_id = _line(db, plan).id
    store.delete_plan_line(db, client.id, line_id, commit=False)
    db.rollback()
    line = db.get(models.MonthlyPlanLine, line_id)
    assert line is not None
    assert line.is_active is True and line.plan_id == plan.id


def test_foreign_line_keeps_http_404_and_delete_keeps_its_message(planning):
    db, client = planning
    foreign_line = _line(db, _plan(db, client_id=2))
    with pytest.raises(HTTPException) as caught:
        router.delete_plan_line(foreign_line.id, db, client)
    assert (caught.value.status_code, caught.value.detail) == (404, "Monthly plan line not found")
    assert foreign_line.is_active is True
    line = _line(db, _plan(db))
    assert router.delete_plan_line(line.id, db, client) == {"message": "Monthly plan line deleted"}


@pytest.mark.parametrize("same_period", [False, True])
def test_period_copy_replaces_target_and_preserves_source_fields(planning, same_period):
    db, client = planning
    plan = _plan(db)
    source = _line(db, plan, source="manual", source_kind="manual", manual_override=True,
                   cash_treatment="non_cash", target_type="manual", target_id=42)
    target_period = source.target_period if same_period else "2026-11"
    old_target = source if same_period else _line(db, plan, period=target_period, name="Old")
    untouched = _line(db, _plan(db, client_id=2), period=target_period)
    result = router.copy_period_full_replace(schemas.CopyPeriodRequest(
        source_period=source.target_period, target_period=target_period,
    ), db, client)
    db.expire_all()
    assert result == {"status": "success", "copied": 1}
    copied = db.query(models.MonthlyPlanLine).filter_by(
        plan_id=plan.id, target_period=target_period, is_active=True,
    ).one()
    assert copied.id != old_target.id
    assert old_target.is_active is False
    assert source.is_active is (not same_period)
    assert untouched.is_active is True
    assert copied.identity_key
    for field in ("line_type", "target_type", "target_id", "account_id", "source_account_id",
                  "name", "amount", "source", "source_kind", "manual_override", "cash_treatment"):
        assert getattr(copied, field) == getattr(source, field)


def test_period_copy_without_a_plan_copies_nothing_and_makes_no_plan(planning):
    db, client = planning
    result = router.copy_period_full_replace(schemas.CopyPeriodRequest(source_period="2026-10", target_period="2026-11"), db, client)
    assert result == {"status": "success", "copied": 0}
    assert db.query(models.BudgetPlan).count() == 0


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261021_0084_single_budget_plan.py"
    spec = importlib.util.spec_from_file_location("single_plan_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_keeps_each_clients_default_plan_and_deletes_the_rest_with_their_rows():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE budget_plans (id INTEGER PRIMARY KEY, client_id INTEGER, name VARCHAR, is_default BOOLEAN, sort_order INTEGER)",
            "CREATE TABLE monthly_plan_lines (id INTEGER PRIMARY KEY, client_id INTEGER, plan_id INTEGER, target_period VARCHAR)",
            # Client 1: the default comes after an alternative. Client 2: no default; its first plan stays.
            "INSERT INTO budget_plans VALUES (1, 1, 'Lean', 0, 0), (2, 1, 'Baseline', 1, 1), (3, 2, 'B', 0, 1), (4, 2, 'A', 0, 0)",
            "INSERT INTO monthly_plan_lines VALUES (1, 1, 1, '2026-10'), (2, 1, 2, '2026-10'), (3, 2, 3, '2026-10'), (4, 2, 4, '2026-10'),"
            " (5, 1, NULL, '2026-10')",
        ):
            connection.exec_driver_sql(statement)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        plans = connection.exec_driver_sql("SELECT id, client_id, is_default FROM budget_plans ORDER BY id").all()
        lines = connection.exec_driver_sql("SELECT id FROM monthly_plan_lines ORDER BY id").all()
    engine.dispose()
    assert plans == [(2, 1, 1), (4, 2, 1)]
    # A row in no plan is data health's to adopt; the migration leaves it.
    assert lines == [(2,), (4,), (5,)]
