from __future__ import annotations

from scenario_fixtures import goal_scenario_id

from app.services.money_storage import to_minor
from app.domain.journal import Leg
from app.services.ledger_service import create_transaction


from backend.app.domain.money import Money

from datetime import date

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.services import registry_service
    from backend.app.database import Base
    from backend.app.routers.budget_plans import compare_budget_plans, copy_period_full_replace, copy_plan_from
    from backend.app.routers.data_transfer import ImportPayload, export_client_data, import_client_data, validate_import_client_data
    from backend.app.schemas import CopyPeriodRequest, MonthlyPlanLineBatchUpdate, MonthlyPlanLineCreate
    from backend.app.services.accounting_service import get_variance_analysis_for_range, process_transaction
    from backend.app.workflows.monthly_action_workflow import apply_action, create_action
    from backend.app.services.budget_lines import assign_plan_line_identity
    from backend.app.services.budget_plan_service import get_budget_summary
    from backend.app.services.budget_plan_store import create_plan_lines, resolve_budget_plan_id, update_plan_lines
    from backend.app.services.periods import add_months, current_period_key, period_to_range
    from backend.app.services.data_health_service import check_data_health, repair_data_health
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.services import registry_service  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers.budget_plans import compare_budget_plans, copy_period_full_replace, copy_plan_from  # type: ignore[no-redef]
    from app.routers.data_transfer import ImportPayload, export_client_data, import_client_data, validate_import_client_data  # type: ignore[no-redef]
    from app.schemas import CopyPeriodRequest, MonthlyPlanLineBatchUpdate, MonthlyPlanLineCreate  # type: ignore[no-redef]
    from app.services.accounting_service import get_variance_analysis_for_range, process_transaction  # type: ignore[no-redef]
    from app.workflows.monthly_action_workflow import apply_action, create_action  # type: ignore[no-redef]
    from app.services.budget_lines import assign_plan_line_identity  # type: ignore[no-redef]
    from app.services.budget_plan_service import get_budget_summary  # type: ignore[no-redef]
    from app.services.budget_plan_store import create_plan_lines, resolve_budget_plan_id, update_plan_lines  # type: ignore[no-redef]
    from app.services.periods import add_months, current_period_key, period_to_range  # type: ignore[no-redef]
    from app.services.data_health_service import check_data_health, repair_data_health  # type: ignore[no-redef]


def _give_fixture_lines_a_plan(db, client_id: int = 1) -> int:
    """Put the fixture's plan lines on a plan, as whoever wrote them would have.

    These fixtures build MonthlyPlanLine rows without a plan_id, as the legacy
    data did. Two waves moved that out of the application: X9 stopped reads
    creating the plan, and X5 removed the orphan adoption from the write
    resolver, because X5 also removed the only thing that produced orphans.
    Adopting these rows is now the fixture's own business, which is where it
    belongs -- the production path writes a plan_id when it writes the line.
    """
    plan_id = resolve_budget_plan_id(db, client_id)
    db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id.is_(None),
    ).update({"plan_id": plan_id}, synchronize_session=False)
    db.commit()
    return plan_id


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_data_health_repairs_plan_line_source_from_posted_transaction() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        payable = models.Account(client_id=1, name="long payable", account_type="liability")
        beauty = models.Account(client_id=1, name="beauty", account_type="expense")
        db.add_all([client, payable, beauty])
        db.flush()
        line = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=beauty.id,
            name="beauty",
            amount_minor=to_minor(120000, "JPY"),
            source_account_id=None,
        )
        tx = models.Transaction(
            client_id=1,
            date=date(2026, 5, 10),
            description="credit beauty",
            amount_minor=Money.from_major(str(120000), "JPY").minor,
            currency="JPY",
        )
        db.add_all([line, tx])
        db.commit()
        process_transaction(db, tx, from_account_id=payable.id, to_account_id=beauty.id)

        health = check_data_health(db, 1)
        source_issue = next(issue for issue in health["issues"] if issue["code"] == "plan_line_sources")
        item = next(item for item in source_issue["items"] if item["line_id"] == line.id)
        assert item["repairable"] is True
        assert item["suggested_source_account_id"] == payable.id

        result = repair_data_health(db, 1)
        db.refresh(line)

        assert line.source_account_id == payable.id
        assert any(action["code"] == "plan_line_sources" and action["updated"] == 1 for action in result["actions"])
    finally:
        db.close()


def test_data_export_includes_budget_plan_line_fields_without_legacy_columns() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", username="test", email="test@example.com", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        db.add_all([client, cash, food, plan])
        db.flush()
        line = models.MonthlyPlanLine(
            client_id=1,
            plan_id=plan.id,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            source_account_id=cash.id,
            name="food",
            amount_minor=to_minor(1000, "JPY"),
            source_kind="manual",
            manual_override=True,
        )
        assign_plan_line_identity(line)
        db.add(line)
        db.commit()

        snapshot = export_client_data(db=db, current_client=client)
        exported_line = snapshot["data"]["monthly_plan_lines"][0]

        assert exported_line["plan_id"] == plan.id
        assert exported_line["source_account_id"] == cash.id
        assert exported_line["source_kind"] == "manual"
        assert exported_line["identity_key"]
        assert exported_line["manual_override"] is True
        assert "priority" not in exported_line
        assert "note" not in exported_line
        assert snapshot["data"]["budget_plans"][0]["name"] == "Baseline"
    finally:
        db.close()


def test_data_export_manifest_and_validate_include_monthly_actions() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", username="test", email="test@example.com", general_settings={})
        db.add(client)
        db.add(
            models.MonthlyAction(
                client_id=1,
                source_period="2026-05",
                target_period="2026-06",
                proposal_id="proposal-1",
                kind="set_budget",
                description="Adjust food budget",
                amount_minor=to_minor(12000, "JPY"),
                target_id=10,
                payload={"account_id": 10, "amount": 12000},
                result={},
                status="pending",
                idempotency_key="review:1:2026-05:test",
            )
        )
        db.commit()

        snapshot = export_client_data(db=db, current_client=client)
        payload = ImportPayload(**snapshot)
        validation = validate_import_client_data(payload=payload, current_client=client)

        assert snapshot["version"] == 27
        assert snapshot["manifest"]["counts"]["monthly_actions"] == 1
        assert snapshot["data"]["monthly_actions"][0]["kind"] == "set_budget"
        assert validation["status"] == "valid"
        assert validation["counts"]["monthly_actions"] == 1
    finally:
        db.close()


def test_data_import_round_trip_remaps_account_targets_and_monthly_actions() -> None:
    source_db = _session()
    target_db = _session()
    try:
        source_client = models.Client(id=1, name="source", username="source", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        source_db.add_all([source_client, cash, food, plan])
        source_db.flush()
        source_db.add(
            models.MonthlyPlanLine(
                client_id=1,
                plan_id=plan.id,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                target_id=food.id,
                account_id=food.id,
                source_account_id=cash.id,
                name="food",
                amount_minor=to_minor(15000, "JPY"),
            )
        )
        source_db.add(
            models.MonthlyAction(
                client_id=1,
                source_period="2026-05",
                target_period="2026-06",
                proposal_id="proposal-1",
                kind="set_budget",
                description="Adjust food budget",
                amount_minor=to_minor(15000, "JPY"),
                target_id=food.id,
                payload={"account_id": food.id, "amount": 15000},
                result={"plan_line_id": 1},
                status="pending",
                idempotency_key="review:1:2026-05:roundtrip",
            )
        )
        source_db.commit()

        snapshot = export_client_data(db=source_db, current_client=source_client)
        target_client = models.Client(id=2, name="target", username="target", general_settings={})
        target_db.add(target_client)
        target_db.commit()

        result = import_client_data(payload=ImportPayload(**snapshot), db=target_db, current_client=target_client)

        imported_food = target_db.query(models.Account).filter_by(client_id=2, name="food").one()
        imported_line = target_db.query(models.MonthlyPlanLine).filter_by(client_id=2, name="food").one()
        imported_action = target_db.query(models.MonthlyAction).filter_by(client_id=2, proposal_id="proposal-1").one()

        assert result["status"] == "ok"
        assert imported_line.account_id == imported_food.id
        assert imported_line.target_id == imported_food.id
        assert imported_action.target_id == imported_food.id
        assert imported_action.payload["account_id"] == imported_food.id
    finally:
        source_db.close()
        target_db.close()


def test_data_import_allows_legacy_checksum_mismatch_when_structure_is_valid() -> None:
    source_db = _session()
    target_db = _session()
    try:
        source_client = models.Client(id=1, name="source", username="source", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        source_db.add_all([source_client, cash])
        source_db.commit()

        snapshot = export_client_data(db=source_db, current_client=source_client)
        snapshot["version"] = 2
        snapshot["manifest"]["export_version"] = 2
        snapshot["manifest"]["checksums"]["accounts"] = "legacy-checksum"
        snapshot["manifest"]["payload_checksum"] = "legacy-payload-checksum"
        payload = ImportPayload(**snapshot)
        validation = validate_import_client_data(payload=payload, current_client=source_client)

        assert validation["status"] == "valid"
        assert validation["warning_count"] >= 2

        target_client = models.Client(id=2, name="target", username="target", general_settings={})
        target_db.add(target_client)
        target_db.commit()
        result = import_client_data(payload=payload, db=target_db, current_client=target_client)

        assert result["status"] == "ok"
        assert result["validation"]["status"] == "valid"
    finally:
        source_db.close()
        target_db.close()


def test_data_import_backfills_plan_line_source_identity_for_legacy_payload() -> None:
    source_db = _session()
    target_db = _session()
    try:
        source_client = models.Client(id=1, name="source", username="source", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        source_db.add_all([source_client, cash, food])
        source_db.flush()
        registry_entry = models.RegistryEntry(client_id=1, name='recurring owner', start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly")
        source_db.add(registry_entry)
        source_db.flush()
        recurring = models.RegistryEntry(client_id=1, name='food', amount_minor=to_minor(10000, 'JPY'), source_account_id=cash.id, destination_account_id=food.id, frequency='Monthly', is_active=True, start_date=date(2026, 1, 1), repeat_mode="indefinite")
        source_db.add(recurring)
        source_db.flush()
        line = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            source_account_id=cash.id,
            name="food",
            amount_minor=to_minor(10000, "JPY"),
            source="recurrence",
        )
        assign_plan_line_identity(line)
        source_db.add(line)
        source_db.commit()

        snapshot = export_client_data(db=source_db, current_client=source_client)
        legacy_line = snapshot["data"]["monthly_plan_lines"][0]
        legacy_line.pop("source_kind", None)
        legacy_line.pop("source_id", None)
        legacy_line.pop("identity_key", None)
        # Legacy provenance must not prevent importing the surviving source kind.
        legacy_line["recurring_transaction_id"] = recurring.id
        snapshot["version"] = 3
        snapshot["manifest"]["export_version"] = 3
        snapshot["manifest"]["checksums"]["monthly_plan_lines"] = "legacy"
        snapshot["manifest"]["payload_checksum"] = "legacy"

        target_client = models.Client(id=2, name="target", username="target", general_settings={})
        target_db.add(target_client)
        target_db.commit()
        result = import_client_data(payload=ImportPayload(**snapshot), db=target_db, current_client=target_client)
        imported_line = target_db.query(models.MonthlyPlanLine).filter_by(client_id=2, name="food").one()
        imported_entry = target_db.query(models.RegistryEntry).filter_by(client_id=2, name="food").one()
        assert imported_entry.name == "food"

        assert result["status"] == "ok"
        assert imported_line.source_kind == "recurring"
        assert not hasattr(imported_line, "source_id")
        assert imported_line.identity_key
    finally:
        source_db.close()
        target_db.close()


def test_budget_summary_combines_income_spending_allocations_and_debt() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        nisa = models.Account(client_id=1, name="NISA", account_type="asset")
        loan = models.Account(client_id=1, name="loan", account_type="liability")
        db.add_all([client, salary, cash, food, nisa, loan])
        db.flush()
        registry_service.create_entry(db, 1, {'name': 'salary', 'amount': 200000, 'source_account_id': salary.id, 'destination_account_id': cash.id, 'frequency': 'Monthly', 'is_active': True, "start_date": date(2026, 1, 1), "repeat_mode": "indefinite", "kind": "income" if db.get(models.Account, salary.id).account_type == "income" else {"expense":"expense", "liability":"debt"}.get(db.get(models.Account, cash.id).account_type, "transfer")})
        registry_service.create_entry(db, 1, {'name': 'rent', 'amount': 80000, 'source_account_id': cash.id, 'destination_account_id': food.id, 'frequency': 'Monthly', 'is_active': True, "start_date": date(2026, 1, 1), "repeat_mode": "indefinite", "kind": "income" if db.get(models.Account, cash.id).account_type == "income" else {"expense":"expense", "liability":"debt"}.get(db.get(models.Account, food.id).account_type, "transfer")})
        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="income",
                target_type="manual",
                name="bonus reserve",
                amount_minor=to_minor(100000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount_minor=to_minor(30000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="allocation",
                target_type="account",
                account_id=nisa.id,
                name="NISA",
                amount_minor=to_minor(50000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                name="loan",
                amount_minor=to_minor(20000, "JPY"),
            ),
        ])
        tx = models.Transaction(
            client_id=1,
            date=date(2026, 5, 10),
            description="NISA transfer",
            amount_minor=Money.from_major(str(50000), "JPY").minor,
            currency="JPY",
        )
        db.add(tx)
        db.commit()
        process_transaction(db, tx, from_account_id=cash.id, to_account_id=nisa.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period="2026-05")

        assert summary["total_expected_inflow"] == 100000
        assert summary["monthly_fixed_costs"] == 80000
        assert summary["total_variable_budget"] == 30000
        assert summary["total_allocation_plan"] == 50000
        assert summary["total_debt_plan"] == 20000
        assert summary["remaining_balance"] == 0
        food_budget = next(account for account in summary["expense_accounts"] if account["name"] == "food")
        assert food_budget["recurring_amount"] == 80000
        assert food_budget["sync_status"] == "diff"
        nisa_line = next(line for line in summary["plan_lines"] if line["target_name"] == "NISA")
        assert nisa_line["actual"] == 50000
        assert nisa_line["variance"] == 0
    finally:
        db.close()




def test_set_budget_action_updates_specified_plan_only() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        baseline = models.BudgetPlan(client_id=1, name="Baseline", is_default=True, sort_order=0)
        lean = models.BudgetPlan(client_id=1, name="Lean", is_default=False, sort_order=1)
        db.add_all([client, food, baseline, lean])
        db.flush()
        for plan, amount in [(baseline, 10000), (lean, 20000)]:
            line = models.MonthlyPlanLine(
                client_id=1,
                plan_id=plan.id,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount_minor=to_minor(amount, "JPY"),
            )
            assign_plan_line_identity(line)
            db.add(line)
        db.commit()

        action = create_action(
            db,
            client_id=1,
            source_period="2026-04",
            target_period="2026-05",
            kind="set_budget",
            payload={"account_id": food.id, "amount": 30000, "plan_id": lean.id},
        )
        applied = apply_action(db, client_id=1, action_id=action["id"])

        baseline_line = db.query(models.MonthlyPlanLine).filter_by(
            client_id=1,
            plan_id=baseline.id,
            account_id=food.id,
            target_period="2026-05",
            is_active=True,
        ).one()
        lean_line = db.query(models.MonthlyPlanLine).filter_by(
            client_id=1,
            plan_id=lean.id,
            account_id=food.id,
            target_period="2026-05",
            is_active=True,
        ).one()
        assert applied["result"]["plan_id"] == lean.id
        assert baseline_line.amount == 10000
        assert lean_line.amount == 30000
    finally:
        db.close()


def test_variance_analysis_uses_specified_plan_budget() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        baseline = models.BudgetPlan(client_id=1, name="Baseline", is_default=True, sort_order=0)
        lean = models.BudgetPlan(client_id=1, name="Lean", is_default=False, sort_order=1)
        db.add_all([client, food, baseline, lean])
        db.flush()
        for plan, amount in [(baseline, 10000), (lean, 25000)]:
            line = models.MonthlyPlanLine(
                client_id=1,
                plan_id=plan.id,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount_minor=to_minor(amount, "JPY"),
            )
            assign_plan_line_identity(line)
            db.add(line)
        db.commit()

        baseline_variance = get_variance_analysis_for_range(db, date(2026, 5, 1), date(2026, 5, 31), client_id=1, plan_id=baseline.id)
        lean_variance = get_variance_analysis_for_range(db, date(2026, 5, 1), date(2026, 5, 31), client_id=1, plan_id=lean.id)

        assert baseline_variance["total_budget"] == 10000
        assert baseline_variance["plan_id"] == baseline.id
        assert lean_variance["total_budget"] == 25000
        assert lean_variance["plan_id"] == lean.id
    finally:
        db.close()


def test_create_plan_lines_updates_capsule_contribution_and_monthly_plan_line() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        cap_account = models.Account(client_id=1, name="house capsule", account_type="asset")
        db.add_all([client, cash, food, cap_account])
        db.flush()
        capsule = models.Capsule(
            client_id=1,
            name="House",
            target_amount_minor=to_minor(1000000, "JPY"),
            monthly_contribution_minor=to_minor(10000, "JPY"),
            funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=cap_account.id, target_amount_minor=to_minor(1000000, "JPY") or 0)],
        )
        db.add(capsule)
        db.commit()

        saved = create_plan_lines(db, client_id=1, payloads=[
            MonthlyPlanLineCreate(
                target_period="2026-05",
                line_type="allocation",
                target_type="capsule",
                target_id=capsule.id,
                amount=40000,
            ),
            MonthlyPlanLineCreate(
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                amount=25000,
            ),
        ])

        db.refresh(capsule)
        expense_line = db.query(models.MonthlyPlanLine).filter(
            models.MonthlyPlanLine.client_id == 1,
            models.MonthlyPlanLine.account_id == food.id,
            models.MonthlyPlanLine.target_period == "2026-05",
            models.MonthlyPlanLine.line_type == "expense",
        ).one()

        assert len(saved) == 2
        assert capsule.monthly_contribution == 40000
        assert expense_line.amount == 25000
    finally:
        db.close()


def test_update_plan_lines_requires_existing_id() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, food])
        db.commit()

        try:
            update_plan_lines(db, client_id=1, payloads=[
                MonthlyPlanLineCreate(
                    target_period="2026-05",
                    line_type="expense",
                    target_type="account",
                    account_id=food.id,
                    amount=12000,
                )
            ])
        except ValueError as exc:
            assert "id is required" in str(exc)
        else:
            raise AssertionError("update_plan_lines accepted an id-less payload")

        created = create_plan_lines(db, client_id=1, payloads=[
            MonthlyPlanLineCreate(
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                amount=12000,
            )
        ])[0]
        updated = update_plan_lines(db, client_id=1, payloads=[
            MonthlyPlanLineBatchUpdate(
                id=created.id,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                amount=18000,
            )
        ])[0]

        assert updated.id == created.id
        assert updated.amount == 18000
    finally:
        db.close()


def test_budget_summary_deduplicates_expense_lines_without_writing() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, food])
        db.flush()
        older = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name=food.name,
            amount_minor=to_minor(10000, "JPY"),
        )
        newer = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name=food.name,
            amount_minor=to_minor(15000, "JPY"),
        )
        db.add_all([older, newer])
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period="2026-05")
        accounts = [account for account in summary["expense_accounts"] if account["account_id"] == food.id]
        db.refresh(older)
        db.refresh(newer)

        assert len(accounts) == 1
        assert accounts[0]["plan_line_id"] == newer.id
        assert accounts[0]["amount"] == 15000
        assert older.is_active is True
        assert newer.is_active is True
    finally:
        db.close()


def test_budget_summary_lists_unset_accounts_with_their_actuals() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        bank = models.Account(client_id=1, name="bank", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        travel = models.Account(client_id=1, name="travel", account_type="expense")
        old = models.Account(client_id=1, name="old", account_type="expense", is_active=False)
        salary = models.Account(client_id=1, name="salary", account_type="income")
        nisa = models.Account(client_id=1, name="NISA", account_type="asset")
        card = models.Account(client_id=1, name="card", account_type="liability", liability_kind="card")
        loan = models.Account(client_id=1, name="loan", account_type="liability", liability_kind="loan")
        db.add_all([client, bank, food, travel, old, salary, nisa, card, loan])
        db.flush()
        db.add(models.MonthlyPlanLine(
            client_id=1, target_period="2026-05", line_type="expense", target_type="account",
            account_id=food.id, name="food", amount_minor=to_minor(30000, "JPY"),
        ))
        tx = models.Transaction(
            client_id=1, date=date(2026, 5, 10), description="trip",
            amount_minor=Money.from_major("12000", "JPY").minor, currency="JPY",
        )
        db.add(tx)
        db.commit()
        process_transaction(db, tx, from_account_id=bank.id, to_account_id=travel.id)
        _give_fixture_lines_a_plan(db)

        assert "unset_lines" not in get_budget_summary(db, client_id=1, period="2026-05")
        summary = get_budget_summary(db, client_id=1, period="2026-05", include_unset=True)
        rows = {(line["line_type"], line["name"]): line for line in summary["unset_lines"]}

        assert set(rows) == {
            ("income", "salary"), ("expense", "travel"), ("allocation", "NISA"),
            ("allocation", "bank"), ("drawdown", "bank"),
            ("debt_payment", "card"), ("debt_payment", "loan"), ("borrowing", "loan"), ("drawdown", "NISA"),
        }
        travel_row = rows[("expense", "travel")]
        assert travel_row["id"] is None and travel_row["amount"] == 0
        assert travel_row["budget_amount"] == 0
        assert travel_row["target_type"] == "account" and travel_row["account_id"] == travel.id
        assert travel_row["actual"] == 12000 and travel_row["variance"] == -12000
        assert summary["total_variable_budget"] == 30000
    finally:
        db.close()


def test_data_health_reports_and_repairs_duplicate_plan_lines() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, food])
        db.flush()
        older = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name=food.name,
            amount_minor=to_minor(10000, "JPY"),
        )
        newer = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name=food.name,
            amount_minor=to_minor(15000, "JPY"),
        )
        db.add_all([older, newer])
        db.commit()

        health = check_data_health(db, 1)
        duplicate_issue = next(issue for issue in health["issues"] if issue["code"] == "duplicate_plan_lines")
        assert duplicate_issue["count"] == 1

        result = repair_data_health(db, 1)
        db.refresh(older)
        db.refresh(newer)

        assert any(action["code"] == "duplicate_plan_lines" and action["updated"] == 1 for action in result["actions"])
        assert older.is_active is False
        assert newer.is_active is True
    finally:
        db.close()


def test_db_rejects_duplicate_active_plan_line_identity() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        db.add_all([client, food, plan])
        db.flush()
        first = models.MonthlyPlanLine(
            client_id=1,
            plan_id=plan.id,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name=food.name,
            amount_minor=to_minor(10000, "JPY"),
        )
        duplicate = models.MonthlyPlanLine(
            client_id=1,
            plan_id=plan.id,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name=food.name,
            amount_minor=to_minor(15000, "JPY"),
        )
        assign_plan_line_identity(first)
        assign_plan_line_identity(duplicate)
        db.add_all([first, duplicate])

        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.close()


def test_capsule_allocation_actual_uses_current_journal_claim() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        account = models.Account(client_id=1, name="bank", account_type="asset")
        db.add_all([client, account])
        db.flush()
        capsule = models.Capsule(
            client_id=1,
            name="Emergency Fund",
            target_amount_minor=to_minor(300000, "JPY"),
            monthly_contribution_minor=to_minor(0, "JPY"),
            funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=account.id, target_amount_minor=to_minor(300000, "JPY") or 0)],
        )
        db.add(capsule)
        db.flush()
        source = models.Account(client_id=1, name="source", account_type="asset")
        db.add(source)
        db.flush()
        create_transaction(db, client_id=1, date=date(2026, 5, 1), description="Reserve",
                           amount_minor=120000, currency="JPY",
                           legs=[Leg(account.id, debit=120000, capsule_id=capsule.id), Leg(source.id, credit=120000)])
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="allocation",
            target_type="capsule",
            target_id=capsule.id,
            account_id=account.id,
            name=capsule.name,
            amount_minor=to_minor(50000, "JPY"),
        ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period="2026-05")
        line = next(item for item in summary["plan_lines"] if item["target_type"] == "capsule")

        assert line["actual"] == 120000
    finally:
        db.close()


def test_an_earmark_proposes_its_monthly_amount_before_any_plan_exists() -> None:
    db = _session()
    try:
        account = models.Account(client_id=1, name="savings", account_type="asset")
        db.add_all([models.Client(id=1, name="test", general_settings={}), account])
        db.flush()
        db.add(models.Capsule(
            client_id=1, name="Travel", target_amount_minor=300000, monthly_contribution_minor=20000,
            funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=account.id, target_amount_minor=300000)],
        ))
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        line = next(item for item in summary["plan_lines"] if item["target_type"] == "capsule")

        assert summary["plan_id"] is None
        assert (line["id"], line["account_id"], line["budget_amount"]) == (None, account.id, 20000)
        assert db.query(models.BudgetPlan).count() == 0
    finally:
        db.close()


def test_product_reserve_capsule_allocation_exposes_suggested_amount() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        capsule = models.Capsule(
            client_id=1,
            name="Item Reserve",
            target_amount_minor=to_minor(12000, "JPY"),
            monthly_contribution_minor=to_minor(3000, "JPY"),
            capsule_type="product_pool",
            target_amount_source="linked_products",
            monthly_contribution_source="linked_products",
        )
        db.add_all([client, capsule])
        db.flush()
        db.add(models.Product(
            client_id=1,
            name="Quarterly filter",
            category="home",
            last_unit_price_minor=to_minor(9000, "JPY"),
            units_per_purchase=1,
            frequency_days=90,
            is_asset=False,
            funding_capsule_id=capsule.id,
            budget_treatment="reserve_allocation",
        ))
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="allocation",
            target_type="capsule",
            target_id=capsule.id,
            name=capsule.name,
            amount_minor=to_minor(1000, "JPY"),
        ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period="2026-05")
        line = next(item for item in summary["plan_lines"] if item["target_type"] == "capsule")

        assert line["amount"] == 1000
        assert line["suggested_amount"] == 3000
        assert line["suggested_source"] == "product_reserve"
        assert line["suggested_status"] == "diff"
        assert line["suggested_items"] == [{
            "id": 1,
            "name": "Quarterly filter",
            "amount": 3000,
            "source": "product_reserve",
        }]
    finally:
        db.close()


def test_expense_only_products_are_variable_budget_suggestions() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, food])
        db.flush()
        db.add(models.Product(
            client_id=1,
            name="Meal replacement",
            category="food",
            last_unit_price_minor=to_minor(30000, "JPY"),
            units_per_purchase=1,
            frequency_days=30,
            is_asset=False,
            budget_account_id=food.id,
            budget_treatment="auto",
        ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period="2026-05")
        account = next(item for item in summary["expense_accounts"] if item["account_id"] == food.id)

        assert account["amount"] == 0
        assert account["product_expense_amount"] == 30000
        assert account["product_expense_items"] == [{
            "id": 1,
            "name": "Meal replacement",
            "amount": 30000,
        }]
        assert account["suggested_amount"] == 30000
        assert account["suggested_source"] == "registry"
        assert account["suggested_status"] == "missing"
    finally:
        db.close()



def test_cash_flow_projection_warns_about_unsynced_yearly_income() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        salary = models.Account(client_id=1, name="bonus", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        db.add_all([client, salary, cash])
        db.flush()
        registry_service.create_entry(db, 1, {'name': 'summer bonus', 'amount': 600000, 'source_account_id': salary.id, 'destination_account_id': cash.id, 'frequency': 'Yearly', 'month_of_year': 6, 'is_active': True, "start_date": date(2026, 1, 1), "repeat_mode": "indefinite", "kind": "income" if db.get(models.Account, salary.id).account_type == "income" else {"expense":"expense", "liability":"debt"}.get(db.get(models.Account, cash.id).account_type, "transfer")})
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        may = summary["cash_flow_projection"][0]
        june = summary["cash_flow_projection"][1]

        assert may["period"] == "2026-05"
        assert may["inflow"] == 0
        assert june["period"] == "2026-06"
        assert june["inflow"] == 0
        assert june["setup_warnings"][0]["type"] == "missing_budget"
        assert june["setup_warnings"][0]["amount"] == 600000
    finally:
        db.close()


def test_cash_flow_projection_uses_remaining_current_month_plan_after_actuals() -> None:
    db = _session()
    try:
        current_period = current_period_key()
        next_period = add_months(current_period, 1)
        client = models.Client(id=1, name="test", general_settings={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, salary, cash, food])
        db.flush()
        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                target_period=current_period,
                line_type="income",
                target_type="account",
                account_id=salary.id,
                name="salary",
                amount_minor=to_minor(100000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=current_period,
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount_minor=to_minor(50000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="income",
                target_type="account",
                account_id=salary.id,
                name="salary",
                amount_minor=to_minor(100000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount_minor=to_minor(50000, "JPY"),
            ),
        ])
        income_tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="salary",
            amount_minor=Money.from_major(str(100000), "JPY").minor,
            currency="JPY",
        )
        expense_tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="food",
            amount_minor=Money.from_major(str(30000), "JPY").minor,
            currency="JPY",
        )
        db.add_all([income_tx, expense_tx])
        db.commit()
        process_transaction(db, income_tx, from_account_id=salary.id, to_account_id=cash.id)
        process_transaction(db, expense_tx, from_account_id=cash.id, to_account_id=food.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period=current_period, cash_flow_months=2)
        current_row = summary["cash_flow_projection"][0]
        next_row = summary["cash_flow_projection"][1]

        assert summary["starting_cash"] == 70000
        assert current_row["period"] == current_period
        assert current_row["planned_inflow"] == 100000
        assert current_row["actual_inflow"] == 100000
        assert current_row["remaining_inflow"] == 0
        assert current_row["inflow"] == 0
        assert current_row["planned_expense"] == 50000
        assert current_row["actual_expense"] == 30000
        assert current_row["remaining_expense"] == 20000
        assert current_row["expense"] == 20000
        assert current_row["net_cash"] == -20000
        assert current_row["ending_cash"] == 50000
        assert next_row["period"] == next_period
        assert next_row["planned_inflow"] == 100000
        assert next_row["actual_inflow"] == 0
        assert next_row["remaining_inflow"] == 100000
        assert next_row["inflow"] == 100000
        assert next_row["expense"] == 50000
        assert next_row["net_cash"] == 50000
        assert next_row["ending_cash"] == 100000
    finally:
        db.close()


def test_cash_flow_projection_does_not_double_count_current_month_over_actuals() -> None:
    db = _session()
    try:
        current_period = current_period_key()
        client = models.Client(id=1, name="test", general_settings={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, salary, cash, food])
        db.flush()
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period=current_period,
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name="food",
            amount_minor=to_minor(50000, "JPY"),
        ))
        opening_tx = models.Transaction(
            client_id=1,
            date=period_to_range(add_months(current_period, -1))[0],
            description="opening income",
            amount_minor=Money.from_major(str(100000), "JPY").minor,
            currency="JPY",
        )
        expense_tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="food",
            amount_minor=Money.from_major(str(70000), "JPY").minor,
            currency="JPY",
        )
        db.add_all([opening_tx, expense_tx])
        db.commit()
        process_transaction(db, opening_tx, from_account_id=salary.id, to_account_id=cash.id)
        process_transaction(db, expense_tx, from_account_id=cash.id, to_account_id=food.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period=current_period, cash_flow_months=1)
        current_row = summary["cash_flow_projection"][0]

        assert summary["starting_cash"] == 30000
        assert current_row["expense"] == 0
        assert current_row["actual_expense"] == 70000
        assert current_row["remaining_expense"] == 0
        assert current_row["planned_expense"] == 70000
        assert current_row["net_cash"] == 0
        assert current_row["ending_cash"] == 30000
    finally:
        db.close()


def test_financed_expense_counts_as_budget_usage_without_cash_flow_expense() -> None:
    db = _session()
    try:
        current_period = current_period_key()
        next_period = add_months(current_period, 1)
        client = models.Client(id=1, name="test", general_settings={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        beauty = models.Account(client_id=1, name="beauty", account_type="expense")
        loan = models.Account(client_id=1, name="medical loan", account_type="liability")
        db.add_all([client, salary, cash, beauty, loan])
        db.flush()
        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                target_period=current_period,
                line_type="expense",
                target_type="account",
                account_id=beauty.id,
                source_account_id=loan.id,
                name="beauty",
                amount_minor=to_minor(600000, "JPY"),
                cash_treatment="non_cash",
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=current_period,
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                name="medical loan",
                amount_minor=to_minor(30000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="expense",
                target_type="account",
                account_id=beauty.id,
                source_account_id=loan.id,
                name="beauty",
                amount_minor=to_minor(600000, "JPY"),
                cash_treatment="non_cash",
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                name="medical loan",
                amount_minor=to_minor(30000, "JPY"),
            ),
        ])
        opening_tx = models.Transaction(
            client_id=1,
            date=period_to_range(add_months(current_period, -1))[0],
            description="opening income",
            amount_minor=Money.from_major(str(100000), "JPY").minor,
            currency="JPY",
        )
        financed_expense = models.Transaction(
            client_id=1,
            date=date.today(),
            description="beauty",
            amount_minor=Money.from_major(str(600000), "JPY").minor,
            currency="JPY",
        )
        repayment = models.Transaction(
            client_id=1,
            date=date.today(),
            description="medical loan repayment",
            amount_minor=Money.from_major(str(30000), "JPY").minor,
            currency="JPY",
        )
        db.add_all([opening_tx, financed_expense, repayment])
        db.commit()
        process_transaction(db, opening_tx, from_account_id=salary.id, to_account_id=cash.id)
        process_transaction(db, financed_expense, from_account_id=loan.id, to_account_id=beauty.id)
        process_transaction(db, repayment, from_account_id=cash.id, to_account_id=loan.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period=current_period, cash_flow_months=2)
        current_row = summary["cash_flow_projection"][0]
        next_row = summary["cash_flow_projection"][1]
        expense = next(account for account in summary["expense_accounts"] if account["account_id"] == beauty.id)
        debt_line = next(line for line in summary["plan_lines"] if line["line_type"] == "debt_payment")

        assert expense["balance"] == 600000
        assert expense["cash_treatment"] == "non_cash"
        assert debt_line["actual"] == 30000
        assert summary["starting_cash"] == 70000
        assert current_row["expense"] == 0
        assert current_row["debt"] == 0
        assert current_row["non_cash_budget"] == 0
        assert current_row["ending_cash"] == 70000
        assert next_row["expense"] == 0
        assert next_row["debt"] == 30000
        assert next_row["net_cash"] == -30000
        assert next_row["ending_cash"] == 40000
        assert summary["balance_projection"][0]["liabilities"] == 570000
        assert summary["balance_projection"][0]["net_worth"] == -500000
        assert summary["balance_projection"][1]["liabilities"] == 1140000
        assert summary["balance_projection"][1]["net_worth"] == -1100000
    finally:
        db.close()


def test_auto_cash_treatment_excludes_credit_expense_and_projects_card_payment() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        credit = models.Account(client_id=1, name="credit", account_type="liability", liability_kind="card")
        subscription = models.Account(client_id=1, name="subscription", account_type="expense")
        db.add_all([client, cash, credit, subscription])
        db.flush()
        registry_entry = models.RegistryEntry(client_id=1, name='recurring owner', start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly")
        db.add(registry_entry)
        db.flush()
        recurring = models.RegistryEntry(client_id=1, name='subscription', amount_minor=to_minor(10000, 'JPY'), source_account_id=credit.id, destination_account_id=subscription.id, frequency='Monthly', is_active=True, start_date=date(2026, 1, 1), repeat_mode="indefinite")
        db.add(recurring)
        db.flush()
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period=next_period,
            line_type="expense",
            target_type="account",
            account_id=subscription.id,
            source_account_id=credit.id,
            name="subscription",
            amount_minor=to_minor(10000, "JPY"),
            source="recurrence",
            cash_treatment="auto",
        ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(
            db,
            client_id=1,
            period=next_period,
            cash_flow_start_period=next_period,
            cash_flow_months=1,
        )
        row = summary["cash_flow_projection"][0]

        assert row["period"] == next_period
        assert row["expense"] == 0
        assert row["debt"] == 0
        assert row["net_cash"] == 0
        assert row["setup_warnings"][0]["type"] == "missing_credit_settlement"
        assert row["setup_warnings"][0]["amount"] == 10000
    finally:
        db.close()


def test_cash_flow_splits_same_expense_account_by_source_account_bucket() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        loan = models.Account(client_id=1, name="medical loan", account_type="liability")
        beauty = models.Account(client_id=1, name="beauty", account_type="expense")
        db.add_all([client, cash, loan, beauty])
        db.flush()
        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="expense",
                target_type="account",
                account_id=beauty.id,
                source_account_id=cash.id,
                name="beauty cash",
                amount_minor=to_minor(100000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="expense",
                target_type="account",
                account_id=beauty.id,
                source_account_id=loan.id,
                name="beauty loan",
                amount_minor=to_minor(500000, "JPY"),
            ),
        ])
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(
            db,
            client_id=1,
            period=next_period,
            cash_flow_start_period=next_period,
            cash_flow_months=1,
        )
        row = summary["cash_flow_projection"][0]
        beauty_rows = [account for account in summary["expense_accounts"] if account["account_id"] == beauty.id]

        assert len(beauty_rows) == 2
        assert summary["total_variable_budget"] == 600000
        assert row["expense"] == 100000
        assert row["non_cash_budget"] == 500000
        assert row["asset_flow"] == -100000
        assert row["net_cash"] == -100000
    finally:
        db.close()


def test_balance_projection_tracks_future_liability_financed_expense() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={})
        loan = models.Account(client_id=1, name="loan", account_type="liability")
        beauty = models.Account(client_id=1, name="beauty", account_type="expense")
        db.add_all([client, loan, beauty])
        db.flush()
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period=next_period,
            line_type="expense",
            target_type="account",
            account_id=beauty.id,
            source_account_id=loan.id,
            name="beauty",
            amount_minor=to_minor(500000, "JPY"),
        ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(
            db,
            client_id=1,
            period=next_period,
            cash_flow_start_period=next_period,
            cash_flow_months=1,
        )
        cash_row = summary["cash_flow_projection"][0]
        balance_row = summary["balance_projection"][0]

        assert cash_row["expense"] == 0
        assert cash_row["non_cash_budget"] == 500000
        assert cash_row["net_cash"] == 0
        assert balance_row["liabilities"] == 500000
        assert balance_row["net_worth"] == -500000
    finally:
        db.close()


def test_income_direct_to_asset_counts_as_allocation_actual_without_remaining_cash_outflow() -> None:
    db = _session()
    try:
        current_period = current_period_key()
        client = models.Client(id=1, name="test", general_settings={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        bank = models.Account(client_id=1, name="bank", account_type="asset")
        stock = models.Account(client_id=1, name="employee stock", account_type="asset")
        db.add_all([client, salary, bank, stock])
        db.flush()
        line = models.MonthlyPlanLine(
            client_id=1,
            target_period=current_period,
            line_type="allocation",
            target_type="account",
            account_id=stock.id,
            source_account_id=bank.id,
            name="employee stock",
            amount_minor=to_minor(50000, "JPY"),
        )
        tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="payroll stock contribution",
            amount_minor=Money.from_major(str(54515), "JPY").minor,
            currency="JPY",
        )
        db.add_all([line, tx])
        db.commit()
        process_transaction(db, tx, from_account_id=salary.id, to_account_id=stock.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period=current_period, cash_flow_months=1)
        plan_line = next(item for item in summary["plan_lines"] if item["line_type"] == "allocation")
        row = summary["cash_flow_projection"][0]
        balance_row = summary["balance_projection"][0]

        assert plan_line["actual"] == 54515
        assert plan_line["variance"] == -4515
        assert row["planned_allocation"] == 0
        assert row["actual_allocation"] == 0
        assert row["remaining_allocation"] == 0
        assert row["allocation"] == 0
        assert row["net_cash"] == 0
        assert balance_row["total_assets"] == 54515
    finally:
        db.close()


def test_balance_projection_tracks_debt_payment_and_liability_asset_purchase() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        loan = models.Account(client_id=1, name="loan", account_type="liability")
        nisa = models.Account(client_id=1, name="NISA", account_type="asset")
        db.add_all([client, salary, cash, loan, nisa])
        db.flush()
        opening = models.Transaction(
            client_id=1,
            date=period_to_range(add_months(next_period, -2))[0],
            description="opening borrowing",
            amount_minor=Money.from_major(str(100000), "JPY").minor,
            currency="JPY",
        )
        db.add(opening)
        db.commit()
        process_transaction(db, opening, from_account_id=loan.id, to_account_id=cash.id)

        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                source_account_id=cash.id,
                name="loan repayment",
                amount_minor=to_minor(30000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="allocation",
                target_type="account",
                account_id=nisa.id,
                source_account_id=loan.id,
                name="levered NISA",
                amount_minor=to_minor(50000, "JPY"),
            ),
        ])
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(
            db,
            client_id=1,
            period=next_period,
            cash_flow_start_period=next_period,
            cash_flow_months=1,
        )
        cash_row = summary["cash_flow_projection"][0]
        balance_row = summary["balance_projection"][0]

        assert cash_row["debt"] == 30000
        assert cash_row["net_cash"] == 20000
        assert cash_row["asset_flow"] == 20000
        assert balance_row["total_assets"] == 120000
        assert balance_row["liabilities"] == 120000
        assert balance_row["net_worth"] == 0
    finally:
        db.close()


def test_cash_flow_uses_registry_source_when_saved_budget_line_lacks_source_account() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={})
        loan = models.Account(client_id=1, name="long term payable", account_type="liability")
        beauty = models.Account(client_id=1, name="beauty", account_type="expense")
        db.add_all([client, loan, beauty])
        db.flush()
        db.add(models.RegistryEntry(client_id=1, name='beauty', amount_minor=to_minor(500000, 'JPY'), currency='JPY', frequency='Monthly', budget_account_id=beauty.id, source_account_id=loan.id, destination_account_id=beauty.id, budget_active=True, is_active=True, kind={"service":"expense","allocation":"transfer","debt_payment":"debt"}.get('service', 'service'), start_date=date(2026, 1, 1), repeat_mode="indefinite"))
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period=next_period,
            line_type="expense",
            target_type="account",
            account_id=beauty.id,
            name="beauty",
            amount_minor=to_minor(500000, "JPY"),
            source="registry",
            cash_treatment="auto",
        ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(
            db,
            client_id=1,
            period=next_period,
            cash_flow_start_period=next_period,
            cash_flow_months=1,
        )
        row = summary["cash_flow_projection"][0]
        beauty_row = next(account for account in summary["expense_accounts"] if account["account_id"] == beauty.id)

        assert beauty_row["source_account_id"] == loan.id
        assert row["expense"] == 0
        assert row["non_cash_budget"] == 500000
        assert row["net_cash"] == 0
    finally:
        db.close()


def test_an_unsaved_definition_row_reports_the_months_actual() -> None:
    db = _session()
    try:
        period = current_period_key()
        start, _ = period_to_range(period)
        db.add(models.Client(id=1, name="test", general_settings={}))
        bank = models.Account(client_id=1, name="bank", account_type="asset")
        rent = models.Account(client_id=1, name="rent", account_type="expense")
        db.add_all([bank, rent])
        db.flush()
        db.add(models.RegistryEntry(client_id=1, name='rent', amount_minor=to_minor(80000, 'JPY'), currency='JPY', frequency='Monthly', budget_account_id=rent.id, source_account_id=bank.id, destination_account_id=rent.id, budget_active=True, is_active=True, kind={"service":"expense","allocation":"transfer","debt_payment":"debt"}.get('service', 'service'), start_date=date(2026, 1, 1), repeat_mode="indefinite"))
        tx = models.Transaction(client_id=1, date=start, description="rent", amount_minor=to_minor(80000, "JPY"), currency="JPY")
        db.add(tx)
        db.commit()
        process_transaction(db, tx, from_account_id=bank.id, to_account_id=rent.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period=period)
        line = next(line for line in summary["plan_lines"] if line["account_id"] == rent.id)

        assert line["id"] is None and line["source"] == "registry"
        assert (line["amount"], line["budget_amount"], line["actual"], line["variance"]) == (0, 80000, 80000, 0)
    finally:
        db.close()


def test_credit_expense_creates_credit_settlement_projection() -> None:
    db = _session()
    try:
        period = current_period_key()
        start, _ = period_to_range(period)
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        card = models.Account(client_id=1, name="credit card", account_type="liability", liability_kind="card")
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, cash, card, food])
        db.flush()
        tx = models.Transaction(
            client_id=1,
            date=start,
            description="credit food",
            amount_minor=Money.from_major(str(50000), "JPY").minor,
            currency="JPY",
        )
        db.add(tx)
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period=period,
            line_type="expense",
            target_type="account",
            account_id=food.id,
            source_account_id=card.id,
            name="food",
            amount_minor=to_minor(50000, "JPY"),
        ))
        db.commit()
        process_transaction(db, tx, from_account_id=card.id, to_account_id=food.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(
            db,
            client_id=1,
            period=period,
            cash_flow_start_period=period,
            cash_flow_months=1,
        )
        settlement = next(line for line in summary["plan_lines"] if line.get("source_kind") == "credit_settlement")
        row = summary["cash_flow_projection"][0]

        assert settlement["line_type"] == "debt_payment"
        assert settlement["account_id"] == card.id
        assert settlement["suggested_amount"] == 50000
        # The charge is already posted, so no non-cash budget is left to consume
        # this month; the actual figure is where the 50000 shows up.
        assert row["actual_non_cash_budget"] == 50000
        assert row["non_cash_budget"] == 0
        assert row["debt"] == 0
        assert row["setup_warnings"][0]["type"] == "missing_credit_settlement"
    finally:
        db.close()


def test_credit_settlement_uses_liability_closing_day_and_payment_offset() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        card = models.Account(
            client_id=1,
            name="card",
            account_type="liability",
            liability_kind="card",
            liability_closing_day=15,
            liability_payment_day=27,
            liability_payment_month_offset=1,
            liability_payment_policy="full",
        )
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, card, food])
        db.flush()
        charges = [
            models.Transaction(
                client_id=1,
                date=date(2026, 5, 10),
                description="before close",
                amount_minor=Money.from_major(str(10000), "JPY").minor,
                currency="JPY",
            ),
            models.Transaction(
                client_id=1,
                date=date(2026, 5, 20),
                description="after close",
                amount_minor=Money.from_major(str(20000), "JPY").minor,
                currency="JPY",
            ),
        ]
        db.add_all(charges)
        db.commit()
        for charge in charges:
            process_transaction(db, charge, from_account_id=card.id, to_account_id=food.id)

        _give_fixture_lines_a_plan(db)
        june = get_budget_summary(db, client_id=1, period="2026-06", cash_flow_start_period="2026-06", cash_flow_months=1)
        july = get_budget_summary(db, client_id=1, period="2026-07", cash_flow_start_period="2026-07", cash_flow_months=1)

        june_settlement = next(line for line in june["plan_lines"] if line.get("source_kind") == "credit_settlement")
        july_settlement = next(line for line in july["plan_lines"] if line.get("source_kind") == "credit_settlement")

        assert june_settlement["suggested_amount"] == 10000
        assert july_settlement["suggested_amount"] == 20000
    finally:
        db.close()


def test_credit_settlement_applies_fixed_payment_policy() -> None:
    db = _session()
    try:
        period = "2026-05"
        client = models.Client(id=1, name="test", general_settings={})
        card = models.Account(
            client_id=1,
            name="card",
            account_type="liability",
            liability_kind="card",
            liability_payment_policy="fixed",
            liability_fixed_payment_amount_minor=to_minor(5000, "JPY"),
        )
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, card, food])
        db.flush()
        charge = models.Transaction(
            client_id=1,
            date=date(2026, 5, 10),
            description="credit food",
            amount_minor=Money.from_major(str(20000), "JPY").minor,
            currency="JPY",
        )
        db.add(charge)
        db.commit()
        process_transaction(db, charge, from_account_id=card.id, to_account_id=food.id)

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period=period, cash_flow_start_period=period, cash_flow_months=1)
        settlement = next(line for line in summary["plan_lines"] if line.get("source_kind") == "credit_settlement")

        assert settlement["suggested_amount"] == 5000
        assert settlement["suggested_items"][0]["payment_policy"] == "fixed"
    finally:
        db.close()


def test_credit_settlement_spreads_installment_policy_across_future_months() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        card = models.Account(
            client_id=1,
            name="card",
            account_type="liability",
            liability_kind="card",
            liability_payment_month_offset=1,
            liability_payment_policy="installment",
            liability_installment_months=3,
        )
        equipment = models.Account(client_id=1, name="equipment", account_type="expense")
        db.add_all([client, card, equipment])
        db.flush()
        charge = models.Transaction(
            client_id=1,
            date=date(2026, 5, 10),
            description="installment purchase",
            amount_minor=Money.from_major(str(30000), "JPY").minor,
            currency="JPY",
        )
        db.add(charge)
        db.commit()
        process_transaction(db, charge, from_account_id=card.id, to_account_id=equipment.id)

        amounts = []
        for period in ("2026-06", "2026-07", "2026-08"):
            _give_fixture_lines_a_plan(db)
            summary = get_budget_summary(db, client_id=1, period=period, cash_flow_start_period=period, cash_flow_months=1)
            settlement = next(line for line in summary["plan_lines"] if line.get("source_kind") == "credit_settlement")
            amounts.append(settlement["suggested_amount"])

        assert amounts == [10000, 10000, 10000]
    finally:
        db.close()


def test_cash_flow_reports_asset_transfers_as_internal_movements() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        nisa = models.Account(client_id=1, name="NISA", account_type="asset")
        reserve = models.Account(client_id=1, name="Trip Reserve", account_type="asset")
        defense = models.Account(client_id=1, name="Emergency", account_type="asset")
        db.add_all([client, cash, nisa, reserve, defense])
        db.flush()
        for account, amount in [(nisa, 50000), (reserve, 20000), (defense, 10000)]:
            db.add(models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="allocation",
                target_type="account",
                account_id=account.id,
                source_account_id=cash.id,
                name=account.name,
                amount_minor=to_minor(amount, "JPY"),
            ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(
            db,
            client_id=1,
            period=current_period_key(),
            cash_flow_start_period=next_period,
            cash_flow_months=1,
        )
        row = summary["cash_flow_projection"][0]

        assert row["allocation"] == 0
        assert row["asset_flow"] == 0
        assert row["internal_transfer"] == 80000
        assert row["net_cash"] == 0
    finally:
        db.close()


def test_cash_flow_projection_warns_about_unsynced_product_reserve_capsule() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        capsule = models.Capsule(
            client_id=1,
            name="Item Reserve",
            target_amount_minor=to_minor(12000, "JPY"),
            monthly_contribution_minor=to_minor(3000, "JPY"),
            capsule_type="product_pool",
            target_amount_source="linked_products",
            monthly_contribution_source="linked_products",
        )
        db.add_all([client, capsule])
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        warning = summary["cash_flow_projection"][0]["setup_warnings"][0]

        assert warning["type"] == "missing_product_reserve"
        assert warning["source"] == "product_reserve"
        assert warning["capsule_id"] == capsule.id
        assert warning["amount"] == 3000
    finally:
        db.close()


def test_cash_flow_projection_warns_about_product_reserve_amount_diff() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        capsule = models.Capsule(
            client_id=1,
            name="Item Reserve",
            target_amount_minor=to_minor(12000, "JPY"),
            monthly_contribution_minor=to_minor(3000, "JPY"),
            capsule_type="product_pool",
            target_amount_source="linked_products",
            monthly_contribution_source="linked_products",
        )
        db.add_all([client, capsule])
        db.flush()
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="allocation",
            target_type="capsule",
            target_id=capsule.id,
            name=capsule.name,
            amount_minor=to_minor(1000, "JPY"),
        ))
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period="2026-05")
        warning = summary["cash_flow_projection"][0]["setup_warnings"][0]

        assert warning["type"] == "product_reserve_diff"
        assert warning["budget_amount"] == 1000
        assert warning["amount"] == 3000
    finally:
        db.close()


def test_cash_flow_summary_reports_buffer_and_shortfall_month() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        rent = models.Account(client_id=1, name="rent", account_type="expense")
        db.add_all([client, cash, rent])
        db.flush()
        registry_service.create_entry(db, 1, {'name': 'rent', 'amount': 80000, 'source_account_id': cash.id, 'destination_account_id': rent.id, 'frequency': 'Monthly', 'is_active': True, "start_date": date(2026, 1, 1), "repeat_mode": "indefinite", "kind": "income" if db.get(models.Account, cash.id).account_type == "income" else {"expense":"expense", "liability":"debt"}.get(db.get(models.Account, rent.id).account_type, "transfer")})
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")

        assert summary["cash_flow_summary"] == {
            "runway_months": 12,
            "lowest_cash": 0,
            "required_buffer": 0,
            "shortfall_month": None,
            "horizon_months": 12,
        }
        assert summary["cash_flow_projection"][0]["setup_warnings"][0]["type"] == "missing_budget"
    finally:
        db.close()


def test_recurring_budget_context_converts_currency_to_client_currency() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={"currency": "JPY"})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        subscription = models.Account(client_id=1, name="subscription", account_type="expense")
        db.add_all([client, cash, subscription])
        db.flush()
        db.add(models.ExchangeRate(
            client_id=1,
            base_currency="USD",
            quote_currency="JPY",
            rate=150,
            as_of_date=date(2026, 5, 1),
            source="manual",
        ))
        registry_service.create_entry(db, 1, {'name': 'AI Subscription', 'amount': 20, 'currency': 'USD', 'source_account_id': cash.id, 'destination_account_id': subscription.id, 'frequency': 'Monthly', 'is_active': True, "start_date": date(2026, 1, 1), "repeat_mode": "indefinite", "kind": "income" if db.get(models.Account, cash.id).account_type == "income" else {"expense":"expense", "liability":"debt"}.get(db.get(models.Account, subscription.id).account_type, "transfer")})
        registry_service.create_entry(db, 1, {'name': 'Storage Subscription', 'amount': 1000, 'currency': 'JPY', 'source_account_id': cash.id, 'destination_account_id': subscription.id, 'frequency': 'Monthly', 'is_active': True, "start_date": date(2026, 1, 1), "repeat_mode": "indefinite", "kind": "income" if db.get(models.Account, cash.id).account_type == "income" else {"expense":"expense", "liability":"debt"}.get(db.get(models.Account, subscription.id).account_type, "transfer")})
        db.commit()

        _give_fixture_lines_a_plan(db)
        summary = get_budget_summary(db, client_id=1, period="2026-05")
        subscription_accounts = [item for item in summary["expense_accounts"] if item["name"] == "subscription"]
        account = subscription_accounts[0]

        assert len(subscription_accounts) == 1
        assert account["recurring_amount"] == 4000
        assert account["sync_status"] == "missing"
        assert len(account["registry_entry_ids"]) == 2
    finally:
        db.close()


def test_the_repair_adopts_legacy_null_plan_lines_and_the_resolvers_do_not() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, food])
        db.flush()
        line = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name="food",
            amount_minor=to_minor(12000, "JPY"),
        )
        db.add(line)
        db.commit()

        # A read creates nothing and adopts nothing (X9).
        empty_summary = get_budget_summary(db, client_id=1, period="2026-05")
        db.refresh(line)
        assert empty_summary["plan_id"] is None
        assert empty_summary["plan_lines"] == []
        assert line.plan_id is None
        assert db.query(models.BudgetPlan).count() == 0

        # The write resolver creates the plan but leaves the orphan where it is
        # (X5): nothing produces orphans any more, so adopting one is a repair.
        resolve_budget_plan_id(db, 1)
        db.refresh(line)
        assert db.query(models.BudgetPlan).count() == 1
        assert line.plan_id is None
        assert get_budget_summary(db, client_id=1, period="2026-05")["plan_lines"] == []

        # The repair is where a repair belongs.
        repair_data_health(db, 1)
        summary = get_budget_summary(db, client_id=1, period="2026-05")
        db.refresh(line)

        assert summary["plan_id"] == line.plan_id
        assert summary["total_variable_budget"] == 12000
        assert line.plan_id is not None
    finally:
        db.close()


def test_same_line_identity_is_allowed_across_plans_but_not_within_one_plan() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        baseline = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        house = models.BudgetPlan(client_id=1, name="House")
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, baseline, house, food])
        db.commit()

        payload = {
            "target_period": "2026-05",
            "line_type": "expense",
            "target_type": "account",
            "account_id": food.id,
            "amount": 12000,
        }
        baseline_line = create_plan_lines(db, 1, [MonthlyPlanLineCreate(**payload, plan_id=baseline.id)])[0]
        house_line = create_plan_lines(db, 1, [MonthlyPlanLineCreate(**payload, plan_id=house.id)])[0]

        assert baseline_line.plan_id == baseline.id
        assert house_line.plan_id == house.id
        try:
            create_plan_lines(db, 1, [MonthlyPlanLineCreate(**payload, plan_id=baseline.id)])
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("duplicate line was accepted within the same budget plan")
    finally:
        db.close()


def test_plan_line_create_and_update_reject_foreign_or_missing_plan_ids() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        other_client = models.Client(id=2, name="other", general_settings={})
        other_plan = models.BudgetPlan(client_id=2, name="Other", is_default=True)
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, other_client, other_plan, food])
        db.commit()

        base_payload = {
            "target_period": "2026-05",
            "line_type": "expense",
            "target_type": "account",
            "account_id": food.id,
            "amount": 12000,
        }
        for bad_plan_id in (other_plan.id, 9999):
            try:
                create_plan_lines(db, 1, [MonthlyPlanLineCreate(**base_payload, plan_id=bad_plan_id)])
            except ValueError as exc:
                assert "Budget plan not found" in str(exc)
            else:
                raise AssertionError("create accepted an invalid budget plan")

        created = create_plan_lines(db, 1, [MonthlyPlanLineCreate(**base_payload)])[0]
        try:
            update_plan_lines(db, 1, [
                MonthlyPlanLineBatchUpdate(
                    id=created.id,
                    **base_payload,
                    plan_id=other_plan.id,
                )
            ])
        except ValueError as exc:
            assert "Budget plan not found" in str(exc)
        else:
            raise AssertionError("update accepted a foreign budget plan")
    finally:
        db.close()


def test_budget_plan_router_rejects_invalid_compare_and_self_copy() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        db.add_all([client, plan])
        db.commit()

        for plan_ids in ("", "9999"):
            try:
                compare_budget_plans(
                    plan_ids=plan_ids,
                    start_period="2026-05",
                    months=12,
                    db=db,
                    current_client=client,
                )
            except HTTPException as exc:
                assert exc.status_code in {400, 404}
            else:
                raise AssertionError("compare accepted invalid plan_ids")

        try:
            copy_plan_from(plan.id, source_plan_id=plan.id, db=db, current_client=client)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("copy-from-self was accepted")
    finally:
        db.close()


def test_copy_period_full_replace_only_affects_selected_plan() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        baseline = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        house = models.BudgetPlan(client_id=1, name="House")
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, baseline, house, food])
        db.flush()
        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                plan_id=baseline.id,
                target_period="2026-06",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="baseline target",
                amount_minor=to_minor(5000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                plan_id=house.id,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="house source",
                amount_minor=to_minor(15000, "JPY"),
            ),
            models.MonthlyPlanLine(
                client_id=1,
                plan_id=house.id,
                target_period="2026-06",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="house old target",
                amount_minor=to_minor(7000, "JPY"),
            ),
        ])
        db.commit()

        copy_period_full_replace(
            CopyPeriodRequest(source_period="2026-05", target_period="2026-06", plan_id=house.id),
            db=db,
            current_client=client,
        )

        baseline_target = db.query(models.MonthlyPlanLine).filter_by(
            plan_id=baseline.id,
            target_period="2026-06",
            is_active=True,
        ).one()
        house_targets = db.query(models.MonthlyPlanLine).filter_by(
            plan_id=house.id,
            target_period="2026-06",
            is_active=True,
        ).all()

        assert baseline_target.amount == 5000
        assert len(house_targets) == 1
        assert house_targets[0].name == "house source"
        assert house_targets[0].amount == 15000
    finally:
        db.close()


@pytest.mark.parametrize("stored_amount,definition_amount,with_plan", [
    (12000, None, True), (None, 8000, True), (12000, 8000, True),
    (0, 8000, True), (None, 8000, False),
])
def test_budget_amount_uses_the_saved_override_or_unsaved_definition(stored_amount, definition_amount, with_plan):
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True) if with_plan else None
        db.add_all([client, food, *([plan] if plan else [])])
        db.flush()
        if definition_amount is not None:
            db.add(models.RegistryEntry(client_id=1, name='weekly food', budget_account_id=food.id, amount_minor=to_minor(definition_amount, 'JPY'), kind={"service":"expense","allocation":"transfer","debt_payment":"debt"}.get('expense', 'expense'), start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly"))
        if stored_amount is not None:
            db.add(models.MonthlyPlanLine(client_id=1, plan_id=plan.id, target_period="2026-05",
                                          line_type="expense", target_type="account", account_id=food.id,
                                          name="food", amount_minor=to_minor(stored_amount, "JPY")))
        db.commit()
        summary = get_budget_summary(db, 1, "2026-05", cash_flow_months=1, include_unset=True)
        lines = [line for line in summary["plan_lines"] if line["line_type"] == "expense"]
        assert len(lines) == 1
        line = lines[0]
        assert line["budget_amount"] == (stored_amount if stored_amount is not None else definition_amount)
        assert line["amount"] == (stored_amount or 0)
        assert (line["id"] is not None) == (stored_amount is not None)
        assert line["registry_amount"] == (definition_amount or 0)
        assert len(line.get("registry_entry_ids", [])) == (1 if definition_amount is not None else 0)
        assert db.query(models.MonthlyPlanLine).count() == (1 if stored_amount is not None else 0)
        assert db.query(models.BudgetPlan).count() == int(with_plan)
    finally:
        db.close()


@pytest.mark.parametrize("match", ["none", "exact", "without_source", "entry_name", "zero"])
def test_variance_counts_definitions_only_in_months_without_a_matching_saved_line(match):
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        bank = models.Account(client_id=1, name="bank", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        other = models.Account(client_id=1, name="other", account_type="expense")
        plan = models.BudgetPlan(client_id=1, name="Baseline", is_default=True)
        alternate = models.BudgetPlan(client_id=1, name="Alternate")
        db.add_all([client, bank, food, other, plan, alternate])
        db.flush()
        # Two definitions aggregate into one account movement before matching.
        for name, amount in [("weekly food", 5000), ("other food", 3000)]:
            db.add(models.RegistryEntry(client_id=1, name=name, budget_account_id=food.id, source_account_id=bank.id, amount_minor=to_minor(amount, 'JPY'), kind={"service":"expense","allocation":"transfer","debt_payment":"debt"}.get('expense', 'expense'), start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly"))
        if match != "none":
            db.add(models.MonthlyPlanLine(
                client_id=1, plan_id=plan.id, target_period="2026-05", line_type="expense", target_type="account",
                account_id=other.id if match == "entry_name" else food.id,
                source_account_id=None if match == "without_source" else bank.id,
                name="weekly food" if match == "entry_name" else "food override",
                amount_minor=to_minor(0 if match == "zero" else 12000, "JPY"),
            ))
        # Another plan, month, movement and inactive row cannot hide the definition.
        for values in [dict(plan_id=alternate.id), dict(target_period="2026-06", is_active=False),
                       dict(target_period="2026-07"), dict(target_period="2026-06", line_type="allocation")]:
            fields = dict(client_id=1, plan_id=plan.id, target_period="2026-05", line_type="expense",
                          target_type="account", account_id=food.id, amount_minor=to_minor(99000, "JPY"))
            fields.update(values)
            db.add(models.MonthlyPlanLine(**fields))
        db.commit()
        create_transaction(db, client_id=1, date=date(2026, 5, 10), amount_minor=2000, currency="JPY",
                           description="food", from_account_id=bank.id, to_account_id=food.id)
        db.commit()
        result = get_variance_analysis_for_range(db, date(2026, 5, 1), date(2026, 6, 30), 1, plan.id)
        may = 8000 if match == "none" else 0 if match == "zero" else 12000
        assert result["budget_months"] == ["2026-05", "2026-06"]
        assert result["total_budget"] == may + 8000
        assert result["total_actual"] == 2000
        assert result["total_variance"] == may + 8000 - 2000
        budgets = {item["category"]: item["budget"] for item in result["items"]}
        assert budgets["food"] == (8000 if match == "entry_name" else may + 8000)
        assert budgets["other"] == (12000 if match == "entry_name" else 0)
        assert get_variance_analysis_for_range(db, date(2026, 5, 1), date(2026, 5, 31), 1, alternate.id)["total_budget"] == 99000
    finally:
        db.close()


def test_variance_counts_definitions_without_creating_a_plan():
    db = _session()
    try:
        db.add(models.Client(id=1, name="test", general_settings={}))
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add(food)
        db.flush()
        db.add(models.RegistryEntry(client_id=1, name='food', budget_account_id=food.id, amount_minor=8000, kind={"service":"expense","allocation":"transfer","debt_payment":"debt"}.get('expense', 'expense'), start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly"))
        db.commit()
        result = get_variance_analysis_for_range(db, date(2026, 5, 1), date(2026, 5, 31), 1)
        assert result["plan_id"] is None
        assert result["total_budget"] == 8000
        assert db.query(models.BudgetPlan).count() == 0
        assert db.query(models.MonthlyPlanLine).count() == 0
    finally:
        db.close()
