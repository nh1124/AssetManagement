from scenario_fixtures import goal_scenario_id

from app.services.ledger_valuation import calculate_account_valued_balance
from backend.app.domain.money import Money
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.domain.errors import Invalid
from app.services import capsule_service, ledger_service, registry_service
from app.services.fx_service import get_client_currency
from app.workflows import ledger_entry_workflow, product_workflow
from product_saves import confirmed


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([
            models.Client(id=1, name="Workflow reads"),
            models.Client(id=2, name="Other client"),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_product_account_reads_preserve_type_scope_and_inactive_account_acceptance(db):
    expense = models.Account(client_id=1, name="Supplies", account_type="expense", is_active=False)
    asset = models.Account(client_id=1, name="Cash", account_type="asset")
    other = models.Account(client_id=2, name="Other expense", account_type="expense")
    db.add_all([expense, asset, other])
    db.commit()

    assert ledger_service.get_expense_account(db, 1, expense.id) is expense
    assert ledger_service.get_account(db, 1, expense.id) is expense
    assert ledger_service.get_account(db, 1, asset.id) is asset
    assert ledger_service.get_account(db, 1, other.id) is None
    assert ledger_service.get_account(db, 1, 999999) is None
    data = product_workflow.normalize_product_data(db, 1, {
        "budget_account_id": expense.id, "category": "Old category",
        "budget_treatment": "expense_only", "is_asset": False,
    })
    assert data["category"] == "Supplies"
    product_workflow.validate_budget_account(db, 1, None)
    for account_id in (asset.id, other.id, 999999):
        assert ledger_service.get_expense_account(db, 1, account_id) is None
        with pytest.raises(Invalid) as exc:
            product_workflow.validate_budget_account(db, 1, account_id)
        assert str(exc.value) == "Budget account must be an expense account for this client"


def test_product_funding_reads_refuse_goal_other_client_and_missing_capsules(db):
    goal = models.LifeEvent(scenario_id=goal_scenario_id(db, 1), client_id=1, name="Goal")
    db.add(goal)
    db.flush()
    reserve = models.Capsule(client_id=1, name="Reserve")
    goal_capsule = models.Capsule(client_id=1, name="Goal capsule", life_event_id=goal.id)
    other = models.Capsule(client_id=2, name="Other reserve")
    db.add_all([reserve, goal_capsule, other])
    db.commit()

    assert capsule_service.get_product_funding_capsule(db, 1, reserve.id) is reserve
    product_workflow.validate_funding_capsule(db, 1, reserve.id)
    product_workflow.validate_funding_capsule(db, 1, None)
    for capsule_id in (goal_capsule.id, other.id, 999999):
        assert capsule_service.get_product_funding_capsule(db, 1, capsule_id) is None
        with pytest.raises(Invalid) as exc:
            product_workflow.validate_funding_capsule(db, 1, capsule_id)
        assert str(exc.value) == "Funding capsule must be a non-LifeEvent capsule for this client"


def test_transaction_read_prevents_removing_another_clients_entry(db):
    cash = ledger_service.create_account(db, 1, {"name": "Cash", "account_type": "asset"})
    expense = ledger_service.create_account(db, 1, {"name": "Supplies", "account_type": "expense"})
    currency = get_client_currency(db, 1)
    transaction = ledger_service.create_transaction(
        db, client_id=1, date=date(2026, 10, 11), description="Supplies",
        amount_minor=Money.from_major(str(100), currency).minor, currency=currency,
        from_account_id=cash.id, to_account_id=expense.id,
    )
    db.commit()
    assert ledger_service.get_transaction(db, 1, transaction.id) is transaction
    assert ledger_service.get_transaction(db, 2, transaction.id) is None
    assert ledger_service.get_transaction(db, 1, 999999) is None
    assert ledger_entry_workflow.remove_entry(db, 2, transaction.id) is False
    assert ledger_service.get_transaction(db, 1, transaction.id) is transaction
    assert len(transaction.journal_entries) == 2
    assert (calculate_account_valued_balance(db, cash), calculate_account_valued_balance(db, expense)) == (-100, 100)
