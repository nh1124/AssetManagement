from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.services import budget_plan_store
from backend.app.services import monthly_action_store as store
from backend.app.workflows import monthly_action_workflow as workflow


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add_all([
        models.Client(id=1, name="action-owner", general_settings={}),
        models.Client(id=2, name="other-client", general_settings={}),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _fields(key, **overrides):
    return {
        "source_period": "2026-09",
        "target_period": "2026-10",
        "proposal_id": key,
        "kind": "set_budget",
        "description": "Set the next month's budget",
        "amount": 500,
        "target_id": 17,
        "payload": {"account_id": 17, "amount": 500},
        "result": {},
        "status": "pending",
        "idempotency_key": key,
        **overrides,
    }


def test_get_returns_none_for_unknown_and_other_client_ids(db):
    row = store.create(db, 2, _fields("other"), commit=True)
    assert store.get(db, 1, 999999) is None
    assert store.get(db, 1, row.id) is None
    assert store.get(db, 2, row.id) is row


def test_create_preserves_fields_and_leaves_uncommitted_rows_rollbackable(db):
    fields = _fields("rollbackable")
    row = store.create(db, 1, fields, commit=False)
    row_id = row.id
    assert row_id is not None
    assert db.query(models.MonthlyAction).all() == [row]
    assert row.client_id == 1
    assert all(getattr(row, name) == value for name, value in fields.items())
    db.rollback()
    assert store.get(db, 1, row_id) is None
    assert db.query(models.MonthlyAction).count() == 0

    committed = store.create(db, 1, _fields("committed"), commit=True)
    committed_id = committed.id
    db.rollback()
    assert store.get(db, 1, committed_id) is committed
    assert db.query(models.MonthlyAction).count() == 1


def test_list_for_client_preserves_endpoint_period_filters_order_and_status(db):
    older = datetime(2026, 10, 10)
    newer = datetime(2026, 10, 11)
    first = store.create(db, 1, _fields("first", created_at=older))
    second = store.create(db, 1, _fields("second", created_at=newer, target_period="2026-11"))
    skipped = store.create(db, 1, _fields("skipped", created_at=newer, status="skipped"))
    last = store.create(db, 1, _fields("last", created_at=newer, source_period="2026-08"))
    store.create(db, 2, _fields("other", created_at=datetime(2026, 10, 12)))
    db.commit()

    all_rows = [last, skipped, second, first]
    assert store.list_for_client(db, 1) == all_rows
    assert store.list_for_client(db, 1, period="", target_period="", status="") == all_rows
    assert store.list_for_client(db, 1, period="2026-09") == [skipped, second, first]
    assert store.list_for_client(db, 1, target_period="2026-10") == [last, skipped, first]
    assert store.list_for_client(db, 1, period="2026-09", target_period="2026-10") == [skipped, first]
    assert store.list_for_client(db, 1, status="pending") == [last, second, first]
    assert store.list_for_client(db, 1, period="2026-09", target_period="2026-10", status="pending") == [first]
    assert store.list_for_client(db, 1, status="applied") == []
    assert store.list_for_client(db, 1, period="2026-07") == []
    assert store.list_for_client(db, 1, target_period="2026-12") == []
    for source, target in [(None, None), ("", ""), ("2026-09", None), (None, "2026-10"), ("2026-09", "2026-10")]:
        assert workflow.list_actions(db, 1, source, target) == [
            workflow.action_to_dict(row)
            for row in store.list_for_client(db, 1, period=source, target_period=target)
        ]


def test_list_due_includes_pending_and_failed_through_boundary_month_only(db):
    due_first = store.create(db, 1, _fields("due-first"))
    overdue = store.create(db, 1, _fields("overdue", target_period="2026-09", status="failed"))
    due_last = store.create(db, 1, _fields("due-last", status="failed"))
    store.create(db, 1, _fields("future", target_period="2026-11"))
    store.create(db, 1, _fields("applied", status="applied"))
    store.create(db, 1, _fields("skipped", status="skipped"))
    store.create(db, 1, _fields("no-target", target_period=None))
    store.create(db, 2, _fields("other"))
    db.commit()

    assert store.list_due(db, 1, date(2026, 10, 1)) == [overdue, due_first, due_last]
    assert store.list_due(db, 1, date(2026, 10, 31)) == [overdue, due_first, due_last]
    assert store.list_due(db, 1, date(2026, 9, 30)) == [overdue]
    assert store.list_due(db, 1, date(2026, 8, 31)) == []


def test_apply_set_budget_keeps_plan_line_writes_in_budget_service(db):
    account = models.Account(client_id=1, name="Food", account_type="expense")
    plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
    db.add_all([account, plan])
    db.commit()
    fields = _fields("set-budget", payload={"account_id": account.id, "amount": 1234, "plan_id": plan.id})
    action = store.create(db, 1, fields, commit=True)
    assert db.query(models.MonthlyPlanLine).count() == 0

    with patch.object(workflow, "create_plan_line", wraps=budget_plan_store.create_plan_line) as create_line:
        result = workflow.apply_action(db, 1, action.id)
    create_line.assert_called_once()
    assert create_line.call_args.kwargs == {"commit": False}
    line = db.query(models.MonthlyPlanLine).one()
    assert result["status"] == "applied"
    assert result["result"] == {"plan_line_id": line.id, "target_period": "2026-10", "plan_id": plan.id}
    assert (line.client_id, line.plan_id, line.account_id) == (1, plan.id, account.id)
    assert (line.target_period, line.line_type, line.target_type) == ("2026-10", "expense", "account")
    assert (line.name, line.amount, line.is_active) == ("Food", 1234, True)
    assert (line.source, line.source_kind, line.manual_override, line.cash_treatment) == ("manual", "manual", False, "auto")
    assert line.identity_key

    # Inactive lines were historically revived rather than replaced.
    line.is_active = False
    line.source_account_id = account.id
    line.cash_treatment = "non_cash"
    line.manual_override = True
    db.commit()
    updated = store.create(db, 1, _fields("update-budget", payload={
        "account_id": account.id, "amount": 2345, "plan_id": plan.id,
    }), commit=True)
    with patch.object(workflow, "create_plan_line", wraps=budget_plan_store.create_plan_line) as create_line:
        result = workflow.apply_action(db, 1, updated.id)
    create_line.assert_not_called()
    assert db.query(models.MonthlyPlanLine).one() is line
    assert result["result"]["plan_line_id"] == line.id
    assert (line.amount, line.is_active) == (2345, True)
    assert (line.source_account_id, line.cash_treatment, line.manual_override) == (account.id, "non_cash", True)


def test_apply_set_budget_failure_rolls_back_feature_rows_and_commits_failed_action(db, monkeypatch):
    account = models.Account(client_id=1, name="Food", account_type="expense")
    plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
    db.add_all([account, plan])
    db.commit()
    action = store.create(db, 1, _fields("failed-budget", payload={
        "account_id": account.id, "amount": 1234, "plan_id": plan.id,
    }), commit=True)
    action_id = action.id
    failure = RuntimeError("failure after writing the budget line")
    apply_budget = workflow.DISPATCH["set_budget"]

    def fail_after_write(session, row):
        apply_budget(session, row)
        assert session.query(models.MonthlyPlanLine).count() == 1
        raise failure

    monkeypatch.setitem(workflow.DISPATCH, "set_budget", fail_after_write)
    with patch.object(store, "get", wraps=store.get) as get_action:
        with pytest.raises(RuntimeError) as error:
            workflow.apply_action(db, 1, action_id)
    assert error.value is failure
    db.rollback()
    db.expire_all()
    for model in (
        models.MonthlyPlanLine, models.RegistryEntry, models.RecurringTransaction,
        models.Capsule,
    ):
        assert db.query(model).count() == 0, model.__tablename__
    assert db.query(models.BudgetPlan).count() == 1
    failed = store.get(db, 1, action_id)
    assert failed.status == "failed"
    assert failed.result == {"error": str(failure)}
    assert failed.applied_at is None
    assert get_action.call_count == 2
    assert all(call.args == (db, 1, action_id) for call in get_action.call_args_list)
