from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.routers.budget_plans import compare_budget_plans, copy_period_full_replace, copy_plan_from
    from backend.app.routers.data_transfer import export_client_data
    from backend.app.schemas import CopyPeriodRequest, MonthlyPlanLineBatchUpdate, MonthlyPlanLineCreate
    from backend.app.services.accounting_service import process_transaction
    from backend.app.services.budget_plan_service import add_months, create_plan_lines, current_period_key, get_budget_summary, period_to_range, update_plan_lines
    from backend.app.services.data_health_service import check_data_health, repair_data_health
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers.budget_plans import compare_budget_plans, copy_period_full_replace, copy_plan_from  # type: ignore[no-redef]
    from app.routers.data_transfer import export_client_data  # type: ignore[no-redef]
    from app.schemas import CopyPeriodRequest, MonthlyPlanLineBatchUpdate, MonthlyPlanLineCreate  # type: ignore[no-redef]
    from app.services.accounting_service import process_transaction  # type: ignore[no-redef]
    from app.services.budget_plan_service import add_months, create_plan_lines, current_period_key, get_budget_summary, period_to_range, update_plan_lines  # type: ignore[no-redef]
    from app.services.data_health_service import check_data_health, repair_data_health  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_data_health_repairs_plan_line_source_from_posted_transaction() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
            amount=120000,
            source_account_id=None,
        )
        tx = models.Transaction(
            client_id=1,
            date=date(2026, 5, 10),
            description="credit beauty",
            amount=120000,
            type="CreditExpense",
            from_account_id=payable.id,
            to_account_id=beauty.id,
            currency="JPY",
        )
        db.add_all([line, tx])
        db.commit()
        process_transaction(db, tx)

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
        client = models.Client(id=1, name="test", username="test", email="test@example.com", general_settings={}, ai_config={})
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
            amount=1000,
        )
        db.add(line)
        db.commit()

        snapshot = export_client_data(db=db, current_client=client)
        exported_line = snapshot["data"]["monthly_plan_lines"][0]

        assert exported_line["plan_id"] == plan.id
        assert exported_line["source_account_id"] == cash.id
        assert "priority" not in exported_line
        assert "note" not in exported_line
        assert snapshot["data"]["budget_plans"][0]["name"] == "Baseline"
    finally:
        db.close()


def test_budget_summary_combines_income_spending_allocations_and_debt() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        nisa = models.Account(client_id=1, name="NISA", account_type="asset", role="growth")
        loan = models.Account(client_id=1, name="loan", account_type="liability")
        db.add_all([client, salary, cash, food, nisa, loan])
        db.flush()
        db.add_all([
            models.RecurringTransaction(
                client_id=1,
                name="salary",
                amount=200000,
                type="Income",
                from_account_id=salary.id,
                to_account_id=cash.id,
                frequency="Monthly",
                is_active=True,
            ),
            models.RecurringTransaction(
                client_id=1,
                name="rent",
                amount=80000,
                type="Expense",
                from_account_id=cash.id,
                to_account_id=food.id,
                frequency="Monthly",
                is_active=True,
            ),
        ])
        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="income",
                target_type="manual",
                name="bonus reserve",
                amount=100000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount=30000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="allocation",
                target_type="account",
                account_id=nisa.id,
                name="NISA",
                amount=50000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period="2026-05",
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                name="loan",
                amount=20000,
            ),
        ])
        tx = models.Transaction(
            client_id=1,
            date=date(2026, 5, 10),
            description="NISA transfer",
            amount=50000,
            type="Transfer",
            from_account_id=cash.id,
            to_account_id=nisa.id,
            currency="JPY",
        )
        db.add(tx)
        db.commit()
        process_transaction(db, tx)

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


def test_save_plan_lines_updates_capsule_contribution_and_monthly_plan_line() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        cap_account = models.Account(client_id=1, name="house capsule", account_type="asset", role="earmarked")
        db.add_all([client, cash, food, cap_account])
        db.flush()
        capsule = models.Capsule(
            client_id=1,
            name="House",
            target_amount=1000000,
            monthly_contribution=10000,
            account_id=cap_account.id,
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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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


def test_budget_summary_deactivates_duplicate_expense_lines() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
            amount=10000,
        )
        newer = models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="expense",
            target_type="account",
            account_id=food.id,
            name=food.name,
            amount=15000,
        )
        db.add_all([older, newer])
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        accounts = [account for account in summary["expense_accounts"] if account["account_id"] == food.id]
        db.refresh(older)
        db.refresh(newer)

        assert len(accounts) == 1
        assert accounts[0]["plan_line_id"] == newer.id
        assert accounts[0]["amount"] == 15000
        assert older.is_active is False
        assert newer.is_active is True
    finally:
        db.close()


def test_capsule_allocation_actual_uses_current_holding_balance() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        account = models.Account(client_id=1, name="bank", account_type="asset")
        db.add_all([client, account])
        db.flush()
        capsule = models.Capsule(
            client_id=1,
            name="Emergency Fund",
            target_amount=300000,
            monthly_contribution=0,
            account_id=account.id,
        )
        db.add(capsule)
        db.flush()
        db.add(models.CapsuleHolding(capsule_id=capsule.id, account_id=account.id, held_amount=120000))
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="allocation",
            target_type="capsule",
            target_id=capsule.id,
            account_id=account.id,
            name=capsule.name,
            amount=50000,
        ))
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        line = next(item for item in summary["plan_lines"] if item["target_type"] == "capsule")

        assert line["actual"] == 120000
    finally:
        db.close()


def test_product_reserve_capsule_allocation_exposes_suggested_amount() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        capsule = models.Capsule(
            client_id=1,
            name="Item Reserve",
            target_amount=12000,
            monthly_contribution=3000,
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
            last_unit_price=9000,
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
            amount=1000,
        ))
        db.commit()

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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, food])
        db.flush()
        db.add(models.Product(
            client_id=1,
            name="Meal replacement",
            category="food",
            last_unit_price=30000,
            units_per_purchase=1,
            frequency_days=30,
            is_asset=False,
            budget_account_id=food.id,
            budget_treatment="auto",
        ))
        db.commit()

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


def test_life_event_allocation_is_presented_as_capsule() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        account = models.Account(client_id=1, name="event capsule account", account_type="asset")
        db.add_all([client, account])
        db.flush()
        event = models.LifeEvent(
            client_id=1,
            name="Move",
            target_date=date(2027, 4, 1),
            target_amount=500000,
            priority=2,
        )
        db.add(event)
        db.flush()
        capsule = models.Capsule(
            client_id=1,
            name="Move Capsule",
            target_amount=500000,
            monthly_contribution=0,
            life_event_id=event.id,
            account_id=account.id,
        )
        db.add(capsule)
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period="2026-05",
            line_type="allocation",
            target_type="life_event",
            target_id=event.id,
            name=event.name,
            amount=30000,
        ))
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        line = next(item for item in summary["plan_lines"] if item["line_type"] == "allocation")

        assert line["target_type"] == "capsule"
        assert line["target_id"] == capsule.id
        assert line["target_name"] == "Move Capsule"
    finally:
        db.close()


def test_cash_flow_projection_warns_about_unsynced_yearly_income() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        salary = models.Account(client_id=1, name="bonus", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        db.add_all([client, salary, cash])
        db.flush()
        db.add(models.RecurringTransaction(
            client_id=1,
            name="summer bonus",
            amount=600000,
            type="Income",
            from_account_id=salary.id,
            to_account_id=cash.id,
            frequency="Yearly",
            month_of_year=6,
            is_active=True,
        ))
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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
                amount=100000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=current_period,
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount=50000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="income",
                target_type="account",
                account_id=salary.id,
                name="salary",
                amount=100000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="food",
                amount=50000,
            ),
        ])
        income_tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="salary",
            amount=100000,
            type="Income",
            from_account_id=salary.id,
            to_account_id=cash.id,
            currency="JPY",
        )
        expense_tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="food",
            amount=30000,
            type="Expense",
            from_account_id=cash.id,
            to_account_id=food.id,
            currency="JPY",
        )
        db.add_all([income_tx, expense_tx])
        db.commit()
        process_transaction(db, income_tx)
        process_transaction(db, expense_tx)

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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
            amount=50000,
        ))
        opening_tx = models.Transaction(
            client_id=1,
            date=period_to_range(add_months(current_period, -1))[0],
            description="opening income",
            amount=100000,
            type="Income",
            from_account_id=salary.id,
            to_account_id=cash.id,
            currency="JPY",
        )
        expense_tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="food",
            amount=70000,
            type="Expense",
            from_account_id=cash.id,
            to_account_id=food.id,
            currency="JPY",
        )
        db.add_all([opening_tx, expense_tx])
        db.commit()
        process_transaction(db, opening_tx)
        process_transaction(db, expense_tx)

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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
                amount=600000,
                cash_treatment="non_cash",
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=current_period,
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                name="medical loan",
                amount=30000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="expense",
                target_type="account",
                account_id=beauty.id,
                source_account_id=loan.id,
                name="beauty",
                amount=600000,
                cash_treatment="non_cash",
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                name="medical loan",
                amount=30000,
            ),
        ])
        opening_tx = models.Transaction(
            client_id=1,
            date=period_to_range(add_months(current_period, -1))[0],
            description="opening income",
            amount=100000,
            type="Income",
            from_account_id=salary.id,
            to_account_id=cash.id,
            currency="JPY",
        )
        financed_expense = models.Transaction(
            client_id=1,
            date=date.today(),
            description="beauty",
            amount=600000,
            type="CreditExpense",
            from_account_id=loan.id,
            to_account_id=beauty.id,
            currency="JPY",
        )
        repayment = models.Transaction(
            client_id=1,
            date=date.today(),
            description="medical loan repayment",
            amount=30000,
            type="LiabilityPayment",
            from_account_id=cash.id,
            to_account_id=loan.id,
            currency="JPY",
        )
        db.add_all([opening_tx, financed_expense, repayment])
        db.commit()
        process_transaction(db, opening_tx)
        process_transaction(db, financed_expense)
        process_transaction(db, repayment)

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


def test_auto_cash_treatment_excludes_credit_expense_recurrence_from_cash_flow() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        credit = models.Account(client_id=1, name="credit", account_type="liability")
        subscription = models.Account(client_id=1, name="subscription", account_type="expense")
        db.add_all([client, cash, credit, subscription])
        db.flush()
        recurring = models.RecurringTransaction(
            client_id=1,
            name="subscription",
            amount=10000,
            type="CreditExpense",
            from_account_id=credit.id,
            to_account_id=subscription.id,
            frequency="Monthly",
            is_active=True,
        )
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
            amount=10000,
            source="recurrence",
            recurring_transaction_id=recurring.id,
            cash_treatment="auto",
        ))
        db.commit()

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
        assert row["net_cash"] == 0
    finally:
        db.close()


def test_cash_flow_splits_same_expense_account_by_source_account_bucket() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", role="operating")
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
                amount=100000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="expense",
                target_type="account",
                account_id=beauty.id,
                source_account_id=loan.id,
                name="beauty loan",
                amount=500000,
            ),
        ])
        db.commit()

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
        assert row["operating_flow"] == -100000
        assert row["net_cash"] == -100000
    finally:
        db.close()


def test_balance_projection_tracks_future_liability_financed_expense() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
            amount=500000,
        ))
        db.commit()

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


def test_balance_projection_tracks_debt_payment_and_liability_asset_purchase() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        salary = models.Account(client_id=1, name="salary", account_type="income")
        cash = models.Account(client_id=1, name="cash", account_type="asset", role="operating")
        loan = models.Account(client_id=1, name="loan", account_type="liability")
        nisa = models.Account(client_id=1, name="NISA", account_type="asset", role="growth")
        db.add_all([client, salary, cash, loan, nisa])
        db.flush()
        opening = models.Transaction(
            client_id=1,
            date=period_to_range(add_months(next_period, -2))[0],
            description="opening borrowing",
            amount=100000,
            type="Borrowing",
            from_account_id=loan.id,
            to_account_id=cash.id,
            currency="JPY",
        )
        db.add(opening)
        db.commit()
        process_transaction(db, opening)

        db.add_all([
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="debt_payment",
                target_type="account",
                account_id=loan.id,
                source_account_id=cash.id,
                name="loan repayment",
                amount=30000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                target_period=next_period,
                line_type="allocation",
                target_type="account",
                account_id=nisa.id,
                source_account_id=loan.id,
                name="levered NISA",
                amount=50000,
            ),
        ])
        db.commit()

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
        assert cash_row["net_cash"] == -30000
        assert cash_row["growth_flow"] == 50000
        assert balance_row["operating_assets"] == 70000
        assert balance_row["growth_assets"] == 50000
        assert balance_row["liabilities"] == 120000
        assert balance_row["net_worth"] == 0
    finally:
        db.close()


def test_cash_flow_uses_registry_source_when_saved_budget_line_lacks_source_account() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        loan = models.Account(client_id=1, name="long term payable", account_type="liability")
        beauty = models.Account(client_id=1, name="beauty", account_type="expense")
        db.add_all([client, loan, beauty])
        db.flush()
        db.add(models.RegistryEntry(
            client_id=1,
            name="beauty",
            entry_type="service",
            amount=500000,
            currency="JPY",
            frequency="Monthly",
            transaction_type="CreditExpense",
            line_type="expense",
            budget_account_id=beauty.id,
            source_account_id=loan.id,
            destination_account_id=beauty.id,
            budget_active=True,
            is_active=True,
        ))
        db.add(models.MonthlyPlanLine(
            client_id=1,
            target_period=next_period,
            line_type="expense",
            target_type="account",
            account_id=beauty.id,
            name="beauty",
            amount=500000,
            source="registry",
            cash_treatment="auto",
        ))
        db.commit()

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


def test_cash_flow_reports_asset_role_movements() -> None:
    db = _session()
    try:
        next_period = add_months(current_period_key(), 1)
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", role="operating")
        nisa = models.Account(client_id=1, name="NISA", account_type="asset", role="growth")
        reserve = models.Account(client_id=1, name="Trip Reserve", account_type="asset", role="earmarked")
        defense = models.Account(client_id=1, name="Emergency", account_type="asset", role="defense")
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
                amount=amount,
            ))
        db.commit()

        summary = get_budget_summary(
            db,
            client_id=1,
            period=current_period_key(),
            cash_flow_start_period=next_period,
            cash_flow_months=1,
        )
        row = summary["cash_flow_projection"][0]

        assert row["allocation"] == 80000
        assert row["operating_flow"] == -80000
        assert row["growth_flow"] == 50000
        assert row["earmarked_flow"] == 20000
        assert row["defense_flow"] == 10000
        assert row["net_cash"] == -80000
    finally:
        db.close()


def test_cash_flow_projection_warns_about_unsynced_product_reserve_capsule() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        capsule = models.Capsule(
            client_id=1,
            name="Item Reserve",
            target_amount=12000,
            monthly_contribution=3000,
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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        capsule = models.Capsule(
            client_id=1,
            name="Item Reserve",
            target_amount=12000,
            monthly_contribution=3000,
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
            amount=1000,
        ))
        db.commit()

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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        rent = models.Account(client_id=1, name="rent", account_type="expense")
        db.add_all([client, cash, rent])
        db.flush()
        db.add(models.RecurringTransaction(
            client_id=1,
            name="rent",
            amount=80000,
            type="Expense",
            from_account_id=cash.id,
            to_account_id=rent.id,
            frequency="Monthly",
            is_active=True,
        ))
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
        client = models.Client(id=1, name="test", general_settings={"currency": "JPY"}, ai_config={})
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
        db.add(models.RecurringTransaction(
            client_id=1,
            name="AI Subscription",
            amount=20,
            currency="USD",
            type="Expense",
            from_account_id=cash.id,
            to_account_id=subscription.id,
            frequency="Monthly",
            is_active=True,
        ))
        db.add(models.RecurringTransaction(
            client_id=1,
            name="Storage Subscription",
            amount=1000,
            currency="JPY",
            type="Expense",
            from_account_id=cash.id,
            to_account_id=subscription.id,
            frequency="Monthly",
            is_active=True,
        ))
        db.commit()

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        subscription_accounts = [item for item in summary["expense_accounts"] if item["name"] == "subscription"]
        account = subscription_accounts[0]

        assert len(subscription_accounts) == 1
        assert account["recurring_amount"] == 4000
        assert account["sync_status"] == "missing"
        assert len(account["recurring_transaction_ids"]) == 2
    finally:
        db.close()


def test_legacy_null_plan_lines_are_backfilled_to_default_plan() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
            amount=12000,
        )
        db.add(line)
        db.commit()

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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        other_client = models.Client(id=2, name="other", general_settings={}, ai_config={})
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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
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
                amount=5000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                plan_id=house.id,
                target_period="2026-05",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="house source",
                amount=15000,
            ),
            models.MonthlyPlanLine(
                client_id=1,
                plan_id=house.id,
                target_period="2026-06",
                line_type="expense",
                target_type="account",
                account_id=food.id,
                name="house old target",
                amount=7000,
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
