from app.services.money_storage import to_minor, minor_fields

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
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


def _plan(db, *, client_id=1, name="Plan", **values):
    plan = models.BudgetPlan(client_id=client_id, name=name, **values)
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


def test_create_plan_writes_one_plan_without_disturbing_existing_default(planning):
    db, client = planning
    baseline = _plan(db, name="Baseline", is_default=True)
    created = store.create_plan(db, client.id, schemas.BudgetPlanCreate(
        name="Lean", description="Less spending", sort_order=5,
    ))
    db.expire_all()
    assert db.query(models.BudgetPlan).count() == 2
    assert (created.name, created.description, created.sort_order, created.is_default) == (
        "Lean", "Less spending", 5, False,
    )
    assert db.query(models.BudgetPlan).filter_by(is_default=True).one().id == baseline.id


def test_delete_plan_soft_deletes_lines_and_leaves_orphans_with_null_plan_id(planning):
    db, client = planning
    plan = _plan(db)
    plan_id = plan.id
    lines = [_line(db, plan), _line(db, plan, name="Rent", is_active=False)]
    other_plan = _plan(db, name="Other")
    other_line = _line(db, other_plan)

    assert store.delete_plan(db, client.id, plan_id) is True
    db.expire_all()
    assert db.get(models.BudgetPlan, plan_id) is None
    assert db.query(models.MonthlyPlanLine).count() == 3
    assert all(line.is_active is False and line.plan_id is None for line in lines)
    assert other_line.is_active is True
    assert other_line.plan_id == other_plan.id


@pytest.mark.parametrize("missing", ["unknown_id", "other_client"])
def test_update_and_delete_missing_plan_return_none_and_false_without_writing(planning, missing):
    db, client = planning
    plan = _plan(db, client_id=2)
    plan_id = 999999 if missing == "unknown_id" else plan.id
    writes = []

    def capture_write(_, __, statement, ___, ____, _____):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture_write)
    try:
        assert store.update_plan(db, client.id, plan_id, {"name": "Changed"}) is None
        assert store.delete_plan(db, client.id, plan_id) is False
        assert not db.new and not db.dirty and not db.deleted
        assert db.query(models.BudgetPlan).count() == 1
        assert plan.name == "Plan"
        assert writes == []
    finally:
        event.remove(db.bind, "before_cursor_execute", capture_write)


def test_delete_single_plan_line_soft_deletes_only_that_line(planning):
    db, client = planning
    plan = _plan(db)
    deleted = _line(db, plan)
    kept = _line(db, plan, name="Rent")
    assert store.delete_plan_line(db, client.id, deleted.id) is True
    db.expire_all()
    assert db.query(models.MonthlyPlanLine).count() == 2
    assert deleted.is_active is False
    assert kept.is_active is True
    assert (kept.plan_id, kept.amount) == (plan.id, 100)


def test_list_plans_orders_by_sort_order_then_id_and_scopes_to_client(planning):
    db, client = planning
    last = _plan(db, name="First created", sort_order=10)
    first = _plan(db, name="Z", sort_order=0)
    second = _plan(db, name="A", sort_order=0)
    _plan(db, client_id=2, name="Foreign", sort_order=-1)
    assert store.list_plans(db, client.id) == [first, second, last]


def test_list_plans_returns_empty_without_creating_baseline(planning):
    db, client = planning
    plans = store.list_plans(db, client.id)
    assert plans == []
    assert store.list_plans(db, client.id) == plans
    assert db.query(models.BudgetPlan).count() == 0
    assert not db.new and not db.dirty and not db.deleted


def test_update_plan_changes_supplied_fields_but_preserves_explicit_null_behavior(planning):
    db, client = planning
    plan = _plan(db, description="Keep", sort_order=5, is_default=True)
    updated = store.update_plan(db, client.id, plan.id, schemas.BudgetPlanUpdate(
        name="Renamed", description=None, sort_order=0,
    ))
    db.expire_all()
    assert updated is plan
    assert (plan.name, plan.description, plan.sort_order, plan.is_default) == (
        "Renamed", "Keep", 0, True,
    )


@pytest.mark.parametrize("operation", ["create", "update", "delete", "line_delete", "adopt"])
def test_commit_false_leaves_changes_rollbackable_by_caller(planning, operation):
    db, client = planning
    plan = _plan(db, description="Original")
    line = _line(db, plan)
    default = _plan(db, name="Baseline", is_default=True)
    plan_id, line_id, default_id = plan.id, line.id, default.id
    if operation == "create":
        store.create_plan(db, client.id, {"name": "New"}, commit=False)
    elif operation == "update":
        store.update_plan(db, client.id, plan_id, {"description": "Changed"}, commit=False)
    elif operation == "delete":
        store.delete_plan(db, client.id, plan_id, commit=False)
    elif operation == "line_delete":
        store.delete_plan_line(db, client.id, line_id, commit=False)
    else:
        store.set_default_budget_plan(db, client.id, plan_id, commit=False)
    db.rollback()
    assert db.query(models.BudgetPlan).count() == 2
    assert db.get(models.BudgetPlan, plan_id).description == "Original"
    assert db.get(models.BudgetPlan, plan_id).is_default is False
    assert db.get(models.BudgetPlan, default_id).is_default is True
    line = db.get(models.MonthlyPlanLine, line_id)
    assert line.is_active is True and line.plan_id == plan_id


@pytest.mark.parametrize("operation", ["create", "update"])
def test_duplicate_name_remains_http_409_and_writes_nothing(planning, operation):
    db, client = planning
    _plan(db, name="Taken")
    plan = _plan(db, name="Original")
    with pytest.raises(HTTPException) as caught:
        if operation == "create":
            router.create_budget_plan(schemas.BudgetPlanCreate(name="Taken"), db, client)
        else:
            router.update_budget_plan(plan.id, schemas.BudgetPlanUpdate(name="Taken"), db, client)
    assert (caught.value.status_code, caught.value.detail) == (
        409, "A plan with this name already exists",
    )
    assert db.query(models.BudgetPlan).count() == 2
    assert plan.name == "Original"


@pytest.mark.parametrize("operation", ["create", "update"])
def test_integrity_error_remains_http_409_and_rolls_back(planning, operation):
    db, client = planning
    plan = _plan(db)
    failure = IntegrityError("duplicate", {}, Exception("unique constraint"))
    with patch.object(db, "commit", side_effect=failure):
        with pytest.raises(HTTPException) as caught:
            if operation == "create":
                router.create_budget_plan(schemas.BudgetPlanCreate(name="New"), db, client)
            else:
                router.update_budget_plan(plan.id, schemas.BudgetPlanUpdate(name="New"), db, client)
    assert (caught.value.status_code, caught.value.detail) == (
        409, "A plan with this name already exists",
    )
    assert db.query(models.BudgetPlan).count() == 1
    assert plan.name == "Plan"


def test_delete_default_plan_remains_http_400_without_changing_lines(planning):
    db, client = planning
    plan = _plan(db, is_default=True)
    line = _line(db, plan)
    with pytest.raises(HTTPException) as caught:
        router.delete_budget_plan(plan.id, db, client)
    assert (caught.value.status_code, caught.value.detail) == (400, "Cannot delete the default plan")
    assert line.is_active is True
    assert db.query(models.BudgetPlan).count() == 1


def test_missing_plan_and_line_keep_http_404_details(planning):
    db, client = planning
    foreign_plan = _plan(db, client_id=2)
    foreign_line = _line(db, foreign_plan)
    calls = [
        lambda: router.update_budget_plan(foreign_plan.id, schemas.BudgetPlanUpdate(name="New"), db, client),
        lambda: router.delete_budget_plan(foreign_plan.id, db, client),
        lambda: router.adopt_budget_plan(foreign_plan.id, db, client),
        lambda: router.delete_plan_line(foreign_line.id, db, client),
    ]
    for call, detail in zip(calls, ["Budget plan not found"] * 3 + ["Monthly plan line not found"]):
        with pytest.raises(HTTPException) as caught:
            call()
        assert (caught.value.status_code, caught.value.detail) == (404, detail)
    assert foreign_line.is_active is True
    assert foreign_plan.is_default is False


def test_router_deletes_preserve_response_keys_and_messages(planning):
    db, client = planning
    plan = _plan(db)
    line = _line(db, plan)
    assert router.delete_plan_line(line.id, db, client) == {"message": "Monthly plan line deleted"}
    assert router.delete_budget_plan(plan.id, db, client) == {"message": "Budget plan deleted"}


@pytest.mark.parametrize("same_period", [False, True])
def test_period_copy_replaces_target_and_preserves_source_fields(planning, same_period):
    db, client = planning
    plan = _plan(db)
    source = _line(db, plan, source="manual", source_kind="manual", manual_override=True,
                   cash_treatment="non_cash", target_type="manual", target_id=42)
    target_period = source.target_period if same_period else "2026-11"
    old_target = source if same_period else _line(db, plan, period=target_period, name="Old")
    other_plan = _plan(db, name="Other")
    untouched = _line(db, other_plan, period=target_period)
    result = router.copy_period_full_replace(schemas.CopyPeriodRequest(
        plan_id=plan.id, source_period=source.target_period, target_period=target_period,
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


def test_plan_copy_commits_replacement_and_preserves_response(planning):
    db, client = planning
    source = _plan(db, name="Source")
    target = _plan(db, name="Target")
    source_line = _line(db, source, manual_override=True)
    old_target = _line(db, target, name="Old")
    assert router.copy_plan_from(target.id, source.id, db, client) == {"status": "success", "copied": 1}
    db.rollback()
    assert old_target.is_active is False
    copied = db.query(models.MonthlyPlanLine).filter_by(plan_id=target.id, is_active=True).one()
    assert (copied.name, copied.amount, copied.manual_override) == (
        source_line.name, source_line.amount, source_line.manual_override,
    )
