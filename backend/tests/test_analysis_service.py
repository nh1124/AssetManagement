from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.accounting_service import (
        get_balance_sheet,
        get_profit_loss_for_range,
        get_profit_loss_rollup,
        process_transaction,
    )
    from backend.app.services.analysis_service import calculate_idle_money, get_summary
    from backend.app.services.reconcile_service import run_reconcile
    from backend.app.services.report_service import apply_monthly_report_proposal, generate_monthly_report
    from backend.app.services.accounting_service import update_transaction
    from backend.app.services.action_bridge_service import apply_action, create_action
    from backend.app.services.strategy_service import get_roadmap_projection
    from backend.app.services.milestone_service import apply_milestones_from_simulation, preview_milestones_from_simulation
    from backend.app.services.fx_service import update_used_exchange_rates
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.accounting_service import (  # type: ignore[no-redef]
        get_balance_sheet,
        get_profit_loss_for_range,
        get_profit_loss_rollup,
        process_transaction,
    )
    from app.services.analysis_service import calculate_idle_money, get_summary  # type: ignore[no-redef]
    from app.services.reconcile_service import run_reconcile  # type: ignore[no-redef]
    from app.services.report_service import apply_monthly_report_proposal, generate_monthly_report  # type: ignore[no-redef]
    from app.services.accounting_service import update_transaction  # type: ignore[no-redef]
    from app.services.action_bridge_service import apply_action, create_action  # type: ignore[no-redef]
    from app.services.strategy_service import get_roadmap_projection  # type: ignore[no-redef]
    from app.services.milestone_service import apply_milestones_from_simulation, preview_milestones_from_simulation  # type: ignore[no-redef]
    from app.services.fx_service import update_used_exchange_rates  # type: ignore[no-redef]


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
        amount=0,
        type="Transfer",
    )
    db.add(tx)
    db.flush()
    for account, amount in accounts:
        if account.account_type in ("asset", "expense", "item"):
            db.add(models.JournalEntry(transaction_id=tx.id, account_id=account.id, debit=amount, credit=0))
        else:
            db.add(models.JournalEntry(transaction_id=tx.id, account_id=account.id, debit=0, credit=amount))


def test_logical_balance_subtracts_due_recurring_outflow() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", balance=0)
        bank = models.Account(client_id=1, name="bank", account_type="asset", balance=0)
        savings = models.Account(client_id=1, name="savings", account_type="asset", balance=0)
        credit = models.Account(client_id=1, name="credit", account_type="liability", balance=0)
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


def test_foreign_currency_transactions_are_valued_with_exchange_rates() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={"currency": "JPY"}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", balance=0)
        salary = models.Account(client_id=1, name="salary", account_type="income", balance=0)
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
            amount=10,
            type="Income",
            category="salary",
            currency="USD",
            from_account_id=salary.id,
            to_account_id=cash.id,
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        process_transaction(db, tx)

        bs = get_balance_sheet(db, client_id=1)
        pl = get_profit_loss_for_range(db, date.today(), date.today(), client_id=1)

        assert bs["currency"] == "JPY"
        assert bs["total_assets"] == 1500
        assert pl["total_income"] == 1500
    finally:
        db.close()


def test_auto_update_detects_used_currency_once_per_day() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={"currency": "JPY"}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", balance=0)
        salary = models.Account(client_id=1, name="salary", account_type="income", balance=0)
        db.add_all([client, cash, salary])
        db.commit()

        tx = models.Transaction(
            client_id=1,
            date=date.today(),
            description="USD income",
            amount=10,
            type="Income",
            category="salary",
            currency="USD",
            from_account_id=salary.id,
            to_account_id=cash.id,
        )
        db.add(tx)
        db.commit()

        calls = []

        def fetcher(base: str, quote: str) -> dict:
            calls.append((base, quote))
            return {"rate": 150.0, "market_date": "2026-05-04", "provider": "test"}

        first = update_used_exchange_rates(db, 1, today=date(2026, 5, 4), fetcher=fetcher)
        second = update_used_exchange_rates(db, 1, today=date(2026, 5, 4), fetcher=fetcher)

        assert calls == [("USD", "JPY")]
        assert len(first["updated"]) == 1
        assert first["updated"][0]["source"] == "auto:test:2026-05-04"
        assert len(second["skipped"]) == 1
    finally:
        db.close()


def test_roadmap_projection_returns_projection_and_liability_demand() -> None:
    db = _session()
    try:
        today = date.today()
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", balance=0)
        credit = models.Account(client_id=1, name="credit", account_type="liability", balance=0)
        db.add(client)
        db.add_all(
            [
                cash,
                credit,
                models.SimulationConfig(client_id=1, monthly_savings=50000, annual_return=5, inflation_rate=2),
            ]
        )
        db.flush()
        opening = models.Transaction(
            client_id=1,
            date=today,
            description="Opening balances",
            amount=0,
            type="Transfer",
        )
        db.add(opening)
        db.flush()
        db.add_all(
            [
                models.JournalEntry(transaction_id=opening.id, account_id=cash.id, debit=500000, credit=0),
                models.JournalEntry(transaction_id=opening.id, account_id=credit.id, debit=0, credit=100000),
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
        emergency = models.Account(
            client_id=1,
            name="emergency",
            account_type="asset",
            balance=0,
            role="defense",
            role_target_amount=600000,
        )
        brokerage = models.Account(
            client_id=1,
            name="brokerage",
            account_type="asset",
            balance=0,
            role="growth",
        )
        loose_cash = models.Account(
            client_id=1,
            name="loose_cash",
            account_type="asset",
            balance=0,
            role="unassigned",
        )
        db.add(client)
        db.add_all(
            [
                emergency,
                brokerage,
                loose_cash,
            ]
        )
        db.flush()
        _post_opening_balances(db, [(emergency, 800000), (brokerage, 300000), (loose_cash, 150000)])
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


def test_period_pl_and_balance_sheet_respect_explicit_dates() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, id=10, name="cash", account_type="asset", balance=0)
        salary = models.Account(client_id=1, id=11, name="salary", account_type="income", balance=0)
        db.add_all([client, cash, salary])
        db.commit()

        april_income = models.Transaction(
            client_id=1,
            date=date(2026, 4, 30),
            description="April salary",
            amount=100000,
            type="Income",
            category="salary",
            from_account_id=11,
            to_account_id=10,
        )
        may_income = models.Transaction(
            client_id=1,
            date=date(2026, 5, 1),
            description="May salary",
            amount=200000,
            type="Income",
            category="salary",
            from_account_id=11,
            to_account_id=10,
        )
        db.add_all([april_income, may_income])
        db.commit()
        process_transaction(db, april_income)
        process_transaction(db, may_income)

        april_bs = get_balance_sheet(db, date(2026, 4, 30), client_id=1)
        may_pl = get_profit_loss_for_range(db, date(2026, 5, 1), date(2026, 5, 31), client_id=1)

        assert april_bs["net_worth"] == 100000
        assert may_pl["total_income"] == 200000
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


def test_simulation_milestones_preview_and_apply_persist_source_snapshot() -> None:
    db = _session()
    try:
        today = date.today()
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", balance=0)
        db.add_all(
            [
                client,
                cash,
                models.SimulationConfig(
                    client_id=1,
                    monthly_savings=120000,
                    annual_return=5,
                    volatility=10,
                    inflation_rate=2,
                ),
            ]
        )
        db.flush()
        _post_opening_balances(db, [(cash, 100000)])
        goal = models.LifeEvent(
            client_id=1,
            name="House",
            target_date=date(today.year + 2, today.month, min(today.day, 28)),
            target_amount=1000000,
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
        assert created[0].source_snapshot["allocated_monthly_savings"] == 120000
        assert created[-1].target_amount == 1000000
    finally:
        db.close()
