from __future__ import annotations

from scenario_fixtures import goal_scenario_id

from app.services.money_storage import to_minor
from app.services.ledger_service import create_transaction
from app.domain.journal import Leg


from backend.app.domain.money import Money

from datetime import date, timedelta

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.accounting_service import (
        get_balance_sheet,
        get_account_flows_for_range,
        get_account_transactions_for_range,
        get_profit_loss_for_range,
        process_transaction,
    )
    from backend.app.services.analysis_service import get_summary
    from backend.app.services.budget_plan_store import resolve_budget_plan_id
    from backend.app.services.periods import current_period_key
    from backend.app.services.report_service import apply_monthly_report_proposal, generate_monthly_report
    from backend.app.services.accounting_service import update_transaction
    from backend.app.workflows.monthly_action_workflow import apply_action, create_action
    from backend.app.services.strategy_service import get_roadmap_projection
    from backend.app.services.milestone_service import apply_milestones_from_simulation, preview_milestones_from_simulation
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.accounting_service import (  # type: ignore[no-redef]
        get_balance_sheet,
        get_account_flows_for_range,
        get_account_transactions_for_range,
        get_profit_loss_for_range,
        process_transaction,
    )
    from app.services.analysis_service import get_summary  # type: ignore[no-redef]
    from app.services.budget_plan_store import resolve_budget_plan_id  # type: ignore[no-redef]
    from app.services.periods import current_period_key  # type: ignore[no-redef]
    from app.services.report_service import apply_monthly_report_proposal, generate_monthly_report  # type: ignore[no-redef]
    from app.services.accounting_service import update_transaction  # type: ignore[no-redef]
    from app.workflows.monthly_action_workflow import apply_action, create_action  # type: ignore[no-redef]
    from app.services.strategy_service import get_roadmap_projection  # type: ignore[no-redef]
    from app.services.milestone_service import apply_milestones_from_simulation, preview_milestones_from_simulation  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return TestingSessionLocal()


def _post_opening_balances(db, accounts: list[tuple[models.Account, float]]) -> None:
    tx = models.Transaction(
        client_id=accounts[0][0].client_id,
        date=date.today(),
        description="Opening balances",
        amount_minor=Money.from_major(str(0), "JPY").minor,
        )
    db.add(tx)
    db.flush()
    for account, amount in accounts:
        if account.account_type in ("asset", "expense"):
            db.add(models.JournalEntry(transaction_id=tx.id, account_id=account.id, debit_minor=Money.from_major(str(amount), tx.currency).minor, credit_minor=Money.from_major(str(0), tx.currency).minor))
        else:
            db.add(models.JournalEntry(transaction_id=tx.id, account_id=account.id, debit_minor=Money.from_major(str(0), tx.currency).minor, credit_minor=Money.from_major(str(amount), tx.currency).minor))


def test_logical_balance_follows_the_plan_and_ignores_the_recurring_definition() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        bank = models.Account(client_id=1, name="bank", account_type="asset")
        savings = models.Account(client_id=1, name="savings", account_type="asset")
        credit = models.Account(client_id=1, name="credit", account_type="liability")
        db.add(client)
        db.add_all(
            [
                cash,
                bank,
                savings,
                credit,
            ]
        )
        db.flush()
        _post_opening_balances(db, [(cash, 700000), (bank, 300000), (credit, 100000)])
        emergency = models.Capsule(
            client_id=1, name="Emergency", target_amount_minor=100000,
            monthly_contribution_minor=10000,
        )
        db.add(emergency)
        db.flush()
        create_transaction(db, client_id=1, date=date.today(), description="Emergency reserve",
                           amount_minor=25000, currency="JPY",
                           legs=[Leg(savings.id, debit=25000, capsule_id=emergency.id), Leg(cash.id, credit=25000)])
        rent = models.Account(client_id=1, name="rent", account_type="expense")
        db.add(rent)
        db.flush()
        registry_entry = models.RegistryEntry(client_id=1, name='recurring owner', start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly")
        db.add(registry_entry)
        db.flush()
        db.add(
            models.RegistryEntry(client_id=1, name='Rent', amount_minor=to_minor(50000, 'JPY'), frequency='Monthly', next_due_date=date.today() + timedelta(days=10), is_active=True, destination_account_id=rent.id, start_date=date(2026, 1, 1), repeat_mode="indefinite")
        )
        db.commit()

        db.add(
            models.MonthlyPlanLine(
                client_id=1,
                plan_id=resolve_budget_plan_id(db, 1),
                target_period=current_period_key(),
                line_type="expense",
                account_id=rent.id,
                name="Rent plan",
                amount_minor=to_minor(50000, "JPY"),
                is_active=True,
            )
        )
        db.commit()

        summary = get_summary(db, client_id=1)

        # The 50,000 is subtracted once, from the plan; the definition contributes nothing.
        assert summary["effective_cash"] == 825000
        assert summary["logical_balance"] == 825000
    finally:
        db.close()


def test_update_transaction_rebuilds_journal_and_revalues_balances() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        db.add(client)
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([cash, food])
        db.commit()

        tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="Lunch",
            amount_minor=Money.from_major(str(1000), "JPY").minor,
            )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        process_transaction(db, tx, from_account_id=cash.id, to_account_id=food.id)

        class Payload:
            def model_dump(self, exclude_unset: bool = False) -> dict:
                return {"amount": 1500, "description": "Lunch edited"}

        updated = update_transaction(db, tx.id, Payload(), client_id=1)

        assert updated.description == "Lunch edited"
        assert updated.amount == 1500
        assert db.query(models.JournalEntry).filter(
            models.JournalEntry.transaction_id == tx.id
        ).count() == 2
        from app.services.ledger_valuation import calculate_account_valued_balances
        balances = calculate_account_valued_balances(db, [cash, food])
        assert balances == {cash.id: -1500, food.id: 1500}
    finally:
        db.close()


def test_foreign_currency_transactions_are_valued_with_exchange_rates() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={"currency": "JPY"})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        salary = models.Account(client_id=1, name="salary", account_type="income")
        db.add(client)
        db.add_all([cash, salary])
        db.add(
            models.ExchangeRate(
                client_id=1,
                base_currency="USD",
                quote_currency="JPY",
                rate=150,
                as_of_date=date.today(),
                source="manual",
            )
        )
        db.commit()

        tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="USD income",
            amount_minor=Money.from_major(str(10), "USD").minor,
            currency="USD",
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        process_transaction(db, tx, from_account_id=salary.id, to_account_id=cash.id)

        bs = get_balance_sheet(db, client_id=1)
        pl = get_profit_loss_for_range(db, date.today(), date.today(), client_id=1)

        assert bs["currency"] == "JPY"
        assert bs["total_assets"] == 1500
        assert pl["total_income"] == 1500
    finally:
        db.close()




def test_roadmap_projection_returns_projection_and_liability_demand() -> None:
    db = _session()
    try:
        today = date.today()
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        credit = models.Account(client_id=1, name="credit", account_type="liability")
        db.add(client)
        db.add_all(
            [
                cash,
                credit,
                models.SimulationConfig(client_id=1, monthly_savings_minor=to_minor(50000, "JPY"), annual_return=5, inflation_rate=2),
            ]
        )
        db.flush()
        opening = models.Transaction(
            client_id=1,
            date=today,
            description="Opening balances",
            amount_minor=Money.from_major(str(0), "JPY").minor,
            )
        db.add(opening)
        db.flush()
        db.add_all(
            [
                models.JournalEntry(transaction_id=opening.id, account_id=cash.id, debit_minor=Money.from_major(str(500000), opening.currency).minor, credit_minor=Money.from_major(str(0), opening.currency).minor),
                models.JournalEntry(transaction_id=opening.id, account_id=credit.id, debit_minor=Money.from_major(str(0), opening.currency).minor, credit_minor=Money.from_major(str(100000), opening.currency).minor),
            ]
        )
        goal = models.LifeEvent(scenario_id=goal_scenario_id(db, 1),
            client_id=1,
            name="House",
            target_date=date(today.year + 2, 12, 31),
            target_amount_minor=to_minor(1000000, "JPY"),
            priority=1,
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        db.add(
            models.Milestone(
                client_id=1,
                life_event_id=goal.id,
                date=date(today.year + 1, 12, 31),
                target_amount_minor=to_minor(400000, "JPY"),
                note="Halfway",
            )
        )
        db.commit()

        result = get_roadmap_projection(
            db,
            client_id=1,
            years=3,
            annual_return=5,
            inflation=2,
            monthly_savings=50000,
        )

        assert set(result) >= {"history", "projection", "liability_demand", "milestones"}
        assert len(result["projection"]) == 4
        assert result["projection"][0]["p50"] == 400000
        assert result["liability_demand"][-1]["cumulative_target"] == 1000000
        assert result["milestones"][0]["life_event_name"] == "House"
        assert result["roadmap_progression"] in {"On Track", "At Risk", "Off Track"}
    finally:
        db.close()






def test_period_pl_and_balance_sheet_respect_explicit_dates() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, id=10, name="cash", account_type="asset")
        salary = models.Account(client_id=1, id=11, name="salary", account_type="income")
        db.add_all([client, cash, salary])
        db.commit()

        april_income = models.Transaction(
            client_id=1,
            date=date(2026, 4, 30),
            description="April salary",
            amount_minor=Money.from_major(str(100000), "JPY").minor,
        )
        may_income = models.Transaction(
            client_id=1,
            date=date(2026, 5, 1),
            description="May salary",
            amount_minor=Money.from_major(str(200000), "JPY").minor,
        )
        db.add_all([april_income, may_income])
        db.commit()
        process_transaction(db, april_income, from_account_id=11, to_account_id=10)
        process_transaction(db, may_income, from_account_id=11, to_account_id=10)

        april_bs = get_balance_sheet(db, date(2026, 4, 30), client_id=1)
        may_pl = get_profit_loss_for_range(db, date(2026, 5, 1), date(2026, 5, 31), client_id=1)

        assert april_bs["net_worth"] == 100000
        assert may_pl["total_income"] == 200000
    finally:
        db.close()


def test_account_flows_and_account_transactions_use_journal_sides() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={"currency": "JPY"})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        salary = models.Account(client_id=1, name="salary", account_type="income")
        food = models.Account(client_id=1, name="food", account_type="expense")
        db.add_all([client, cash, salary, food])
        db.commit()

        income = models.Transaction(
            client_id=1,
            date=date(2026, 5, 1),
            description="Salary",
            amount_minor=Money.from_major(str(500000), "JPY").minor,
            currency="JPY",
        )
        lunch = models.Transaction(
            client_id=1,
            date=date(2026, 5, 3),
            description="Lunch",
            amount_minor=Money.from_major(str(1200), "JPY").minor,
            currency="JPY",
        )
        db.add(income)
        db.commit()
        process_transaction(db, income, from_account_id=salary.id, to_account_id=cash.id)
        db.add(lunch)
        db.commit()
        process_transaction(db, lunch, from_account_id=cash.id, to_account_id=food.id)

        flows = get_account_flows_for_range(
            db,
            date(2026, 5, 1),
            date(2026, 5, 31),
            grain="month",
            account_types=["asset", "expense", "income"],
            client_id=1,
        )
        rows = {row["account_name"]: row for row in flows["accounts"]}

        assert rows["cash"]["total_debit"] == 500000
        assert rows["cash"]["total_credit"] == 1200
        assert rows["cash"]["normal_balance_delta"] == 498800
        assert rows["salary"]["total_credit"] == 500000
        assert rows["salary"]["normal_balance_delta"] == 500000
        assert rows["food"]["total_debit"] == 1200
        assert rows["food"]["normal_balance_delta"] == 1200
        assert rows["food"]["buckets"][0]["key"] == "2026-05"

        expense_flows = get_account_flows_for_range(
            db,
            date(2026, 5, 1),
            date(2026, 5, 31),
            grain="month",
            account_types=["expense"],
            client_id=1,
        )
        assert [row["account_name"] for row in expense_flows["accounts"]] == ["food"]

        detail = get_account_transactions_for_range(
            db,
            food.id,
            date(2026, 5, 1),
            date(2026, 5, 31),
            client_id=1,
        )
        assert detail["total"] == 1
        assert detail["items"][0]["debit"] == 1200
        assert detail["items"][0]["credit"] == 0
        assert detail["items"][0]["counterpart_accounts"][0]["account_name"] == "cash"
    finally:
        db.close()


def test_review_action_set_budget_applies_to_target_period() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={})
        account = models.Account(client_id=1, id=20, name="food", account_type="expense")
        db.add_all([client, account])
        db.commit()

        action = create_action(
            db,
            client_id=1,
            source_period="2026-04",
            target_period="2026-05",
            kind="set_budget",
            description="Set food budget",
            payload={"account_id": 20, "amount": 45000},
        )
        applied = apply_action(db, client_id=1, action_id=action["id"])
        budget = db.query(models.MonthlyPlanLine).filter(
            models.MonthlyPlanLine.client_id == 1,
            models.MonthlyPlanLine.account_id == 20,
            models.MonthlyPlanLine.target_period == "2026-05",
            models.MonthlyPlanLine.line_type == "expense",
        ).one()

        assert applied["status"] == "applied"
        assert budget.amount == 45000
    finally:
        db.close()


def test_simulation_milestones_preview_and_apply_persist_source_snapshot() -> None:
    db = _session()
    try:
        today = date.today()
        client = models.Client(id=1, name="test", general_settings={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        db.add_all(
            [
                client,
                cash,
                models.SimulationConfig(
                    client_id=1,
                    monthly_savings_minor=to_minor(120000, "JPY"),
                    annual_return=5,
                    volatility=10,
                    inflation_rate=2,
                ),
            ]
        )
        db.flush()
        _post_opening_balances(db, [(cash, 100000)])
        goal = models.LifeEvent(scenario_id=goal_scenario_id(db, 1),
            client_id=1,
            name="House",
            target_date=date(today.year + 2, today.month, min(today.day, 28)),
            target_amount_minor=to_minor(1000000, "JPY"),
            priority=1,
        )
        db.add(goal)
        db.commit()

        preview = preview_milestones_from_simulation(
            db,
            client_id=1,
            life_event_id=goal.id,
            basis="deterministic",
            interval="annual",
            mode="replace",
        )
        created = apply_milestones_from_simulation(
            db,
            client_id=1,
            life_event_id=goal.id,
            basis="deterministic",
            interval="annual",
            mode="replace",
        )

        assert preview["items"]
        assert created
        assert all(item.source == "simulation_deterministic" for item in created)
        # A near goal receives its shortfall over the 24 months left, not the whole savings.
        assert created[0].source_snapshot["allocated_monthly_savings"] == pytest.approx(1000000 / 24)
        assert created[-1].target_amount == 1000000
    finally:
        db.close()
