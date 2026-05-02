from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.services.accounting_service import get_profit_loss_rollup, process_transaction
from backend.app.services.analysis_service import calculate_idle_money, get_summary
from backend.app.services.reconcile_service import run_reconcile
from backend.app.services.report_service import apply_monthly_report_proposal, generate_monthly_report
from backend.app.services.accounting_service import update_transaction
from backend.app.services.action_bridge_service import apply_action, create_action
from backend.app.services.strategy_service import get_roadmap_projection


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return TestingSessionLocal()


def test_logical_balance_subtracts_due_recurring_outflow() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        db.add(client)
        db.add_all(
            [
                models.Account(client_id=1, name="cash", account_type="asset", balance=700000),
                models.Account(client_id=1, name="bank", account_type="asset", balance=300000),
                models.Account(client_id=1, name="savings", account_type="asset", balance=0),
                models.Account(client_id=1, name="credit", account_type="liability", balance=-100000),
            ]
        )
        db.add(
            models.Capsule(
                client_id=1,
                name="Emergency",
                target_amount=100000,
                monthly_contribution=10000,
                current_balance=25000,
            )
        )
        db.add(
            models.RecurringTransaction(
                client_id=1,
                name="Rent",
                amount=50000,
                type="Expense",
                frequency="Monthly",
                next_due_date=date.today() + timedelta(days=10),
                is_active=True,
            )
        )
        db.commit()

        summary = get_summary(db, client_id=1)

        assert summary["effective_cash"] == 875000
        assert summary["logical_balance"] == summary["effective_cash"] - 50000
    finally:
        db.close()


def test_monthly_report_action_apply_is_idempotent() -> None:
    db = _session()
    try:
        today = date.today()
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        db.add(client)
        db.add_all(
            [
                models.Account(client_id=1, name="cash", account_type="asset", balance=0),
                models.Account(client_id=1, name="savings", account_type="asset", balance=0),
                models.Account(client_id=1, name="salary", account_type="income", balance=0),
            ]
        )
        goal = models.LifeEvent(
            client_id=1,
            name="Retirement",
            target_date=date(today.year + 5, today.month, min(today.day, 28)),
            target_amount=1000000,
            priority=1,
        )
        db.add(goal)
        db.commit()

        income = models.Transaction(
            client_id=1,
            date=today,
            description="Salary",
            amount=100000,
            type="Income",
            category="salary",
        )
        db.add(income)
        db.commit()
        db.refresh(income)
        process_transaction(db, income)

        report = generate_monthly_report(db, 1, today.year, today.month)
        proposal = next(item for item in report["action_proposals"] if item["auto_executable"])

        first = apply_monthly_report_proposal(db, 1, report["period"], proposal["id"])
        second = apply_monthly_report_proposal(db, 1, report["period"], proposal["id"])

        action_count = db.query(models.MonthlyAction).count()
        monthly_action_tx_count = db.query(models.Transaction).filter(
            models.Transaction.category == "monthly_action"
        ).count()

        assert first["status"] == "applied"
        assert second["status"] == "already_applied"
        assert action_count == 1
        assert monthly_action_tx_count == 1
    finally:
        db.close()


def test_update_transaction_rebuilds_journal_and_keeps_reconcile_clean() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        db.add(client)
        db.add_all(
            [
                models.Account(client_id=1, name="cash", account_type="asset", balance=0),
                models.Account(client_id=1, name="food", account_type="expense", balance=0),
            ]
        )
        db.commit()

        tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="Lunch",
            amount=1000,
            type="Expense",
            category="food",
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        process_transaction(db, tx)

        class Payload:
            def model_dump(self, exclude_unset: bool = False) -> dict:
                return {"amount": 1500, "description": "Lunch edited"}

        updated = update_transaction(db, tx.id, Payload(), client_id=1)

        assert updated.description == "Lunch edited"
        assert updated.amount == 1500
        assert db.query(models.JournalEntry).filter(
            models.JournalEntry.transaction_id == tx.id
        ).count() == 2
        assert run_reconcile(db, client_id=1, fix=False) == []
    finally:
        db.close()


def test_roadmap_projection_returns_projection_and_liability_demand() -> None:
    db = _session()
    try:
        today = date.today()
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        db.add(client)
        db.add_all(
            [
                models.Account(client_id=1, name="cash", account_type="asset", balance=500000),
                models.Account(client_id=1, name="credit", account_type="liability", balance=-100000),
                models.SimulationConfig(client_id=1, monthly_savings=50000, annual_return=5, inflation_rate=2),
            ]
        )
        goal = models.LifeEvent(
            client_id=1,
            name="House",
            target_date=date(today.year + 2, 12, 31),
            target_amount=1000000,
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
                target_amount=400000,
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


def test_idle_money_uses_account_roles_and_defense_excess() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        db.add(client)
        db.add_all(
            [
                models.Account(
                    client_id=1,
                    name="emergency",
                    account_type="asset",
                    balance=800000,
                    role="defense",
                    role_target_amount=600000,
                ),
                models.Account(
                    client_id=1,
                    name="brokerage",
                    account_type="asset",
                    balance=300000,
                    role="growth",
                ),
                models.Account(
                    client_id=1,
                    name="loose_cash",
                    account_type="asset",
                    balance=150000,
                    role="unassigned",
                ),
            ]
        )
        db.commit()

        result = calculate_idle_money(db, client_id=1)

        assert result["idle_money"] == 350000
        assert result["idle_money_rate"] == 28.0
        defense = next(row for row in result["by_role_rows"] if row["role"] == "defense")
        assert defense["status"] == "Over"
        assert defense["idle_component"] == 200000
    finally:
        db.close()


def test_profit_loss_rollup_uses_parent_account_category() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        db.add(client)
        db.add_all(
            [
                models.Account(client_id=1, id=10, name="cash", account_type="asset", balance=0),
                models.Account(client_id=1, id=20, name="food", account_type="expense", balance=0),
                models.Account(client_id=1, id=21, name="lunch", account_type="expense", parent_id=20, balance=0),
            ]
        )
        db.commit()

        tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="Lunch",
            amount=1200,
            type="Expense",
            category="lunch",
            from_account_id=10,
            to_account_id=21,
        )
        db.add(tx)
        db.commit()

        result = get_profit_loss_rollup(db, date.today().year, date.today().month, client_id=1)

        assert result["expenses"] == [{"category": "food", "amount": 1200}]
        assert result["rollup"] is True
    finally:
        db.close()


def test_review_action_set_budget_applies_to_target_period() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        account = models.Account(client_id=1, id=20, name="food", account_type="expense", balance=0)
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
        budget = db.query(models.MonthlyBudget).filter(
            models.MonthlyBudget.client_id == 1,
            models.MonthlyBudget.account_id == 20,
            models.MonthlyBudget.target_period == "2026-05",
        ).one()

        assert applied["status"] == "applied"
        assert budget.amount == 45000
    finally:
        db.close()
