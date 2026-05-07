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

        assert summary["total_expected_inflow"] == 300000
        assert summary["monthly_fixed_costs"] == 80000
        assert summary["total_variable_budget"] == 30000
        assert summary["total_allocation_plan"] == 50000
        assert summary["total_debt_plan"] == 20000
        assert summary["remaining_balance"] == 120000
        nisa_line = next(line for line in summary["plan_lines"] if line["target_name"] == "NISA")
        assert nisa_line["actual"] == 50000
        assert nisa_line["variance"] == 0
    finally:
        db.close()


def test_save_plan_lines_updates_capsule_contribution_and_legacy_budget() -> None:
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


def test_cash_flow_projection_places_yearly_income_in_matching_month() -> None:
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
        assert june["inflow"] == 600000
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
            "runway_months": 0,
            "lowest_cash": -960000,
            "required_buffer": 960000,
            "shortfall_month": "2026-05",
            "horizon_months": 12,
        }
    finally:
        db.close()
