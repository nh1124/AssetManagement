from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.schemas import MonthlyPlanLineCreate
    from backend.app.services.accounting_service import process_transaction
    from backend.app.services.budget_plan_service import get_budget_summary, save_plan_lines
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.schemas import MonthlyPlanLineCreate  # type: ignore[no-redef]
    from app.services.accounting_service import process_transaction  # type: ignore[no-redef]
    from app.services.budget_plan_service import get_budget_summary, save_plan_lines  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


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

        saved = save_plan_lines(db, client_id=1, payloads=[
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


def test_one_time_plan_line_is_saved_and_returned_with_planned_date() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        db.add(client)
        db.commit()

        saved = save_plan_lines(db, client_id=1, payloads=[
            MonthlyPlanLineCreate(
                target_period="2026-05",
                line_type="expense",
                target_type="manual",
                name="one-time repair",
                amount=45000,
                planned_date=date(2026, 5, 20),
                source="one_time",
            ),
            MonthlyPlanLineCreate(
                target_period="2026-05",
                line_type="income",
                target_type="manual",
                name="one-time refund",
                amount=12000,
                planned_date=date(2026, 5, 22),
                source="one_time",
            ),
        ])

        summary = get_budget_summary(db, client_id=1, period="2026-05")
        expense = next(account for account in summary["expense_accounts"] if account["name"] == "one-time repair")
        income = next(line for line in summary["plan_lines"] if line["name"] == "one-time refund")

        assert len(saved) == 2
        assert summary["total_variable_budget"] == 45000
        assert summary["total_expected_inflow"] == 12000
        assert expense["source"] == "one_time"
        assert expense["planned_date"] == "2026-05-20"
        assert expense["plan_line_id"] == saved[0].id
        assert income["source"] == "one_time"
        assert income["planned_date"] == "2026-05-22"
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
