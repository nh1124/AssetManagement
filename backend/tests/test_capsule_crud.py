from app.services.ledger_valuation import calculate_account_valued_balance
from app.services.money_storage import to_minor

from backend.app.domain.money import Money
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.domain.errors import NotFound
from app.routers import capsules as capsule_router
from app.services import capsule_service, ledger_service
from app.services.capsule_service import delete_capsule
from app.services.fx_service import get_client_currency
from app.workflows import capsule_workflow


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([
            models.Client(id=1, name="Capsule CRUD", general_settings={}, ai_config={}),
            models.Client(id=2, name="Other client", general_settings={}, ai_config={}),
        ])
        session.commit()
        yield session
    engine.dispose()


def _capsule(db, *, client_id=1):
    suffix = db.query(models.Capsule).filter_by(client_id=client_id).count()
    cash = models.Account(client_id=client_id, name=f"Cash {suffix}", account_type="asset")
    reserve = models.Account(client_id=client_id, name=f"Reserve {suffix}", account_type="asset", role="earmarked")
    db.add_all([cash, reserve])
    db.flush()
    capsule = models.Capsule(
        client_id=client_id, name="Savings", account_id=reserve.id,
        target_amount_minor=to_minor(500, "JPY"), monthly_contribution_minor=to_minor(10, "JPY"), current_balance_minor=to_minor(123, "JPY"),
    )
    db.add(capsule)
    db.commit()
    return capsule, cash, reserve


def _journal_rows(db):
    return [
        (row.id, row.transaction_id, row.account_id, row.debit, row.credit)
        for row in db.query(models.JournalEntry).order_by(models.JournalEntry.id)
    ]


def _transaction_rows(db):
    return [
        (row.id, row.client_id, row.date, row.description, row.amount, row.currency)
        for row in db.query(models.Transaction).order_by(models.Transaction.id)
    ]


def test_delete_capsule_preserves_every_journal_entry_and_transaction_and_balances_books(db):
    capsule, cash, reserve = _capsule(db)
    capsule_id, account_id = capsule.id, reserve.id
    currency = get_client_currency(db, 1)
    for amount, source, destination in [(500, cash.id, reserve.id), (75, reserve.id, cash.id)]:
        ledger_service.create_transaction(
            db, client_id=1, date=date(2026, 10, 11), description="Reserve transfer",
            amount_minor=Money.from_major(str(amount), currency).minor, currency=currency,
            from_account_id=source, to_account_id=destination,
        )
    db.commit()
    before_entries, before_transactions = _journal_rows(db), _transaction_rows(db)
    assert len(before_entries) == 4

    assert delete_capsule(db, 1, capsule_id)
    db.expire_all()

    assert _journal_rows(db) == before_entries
    assert _transaction_rows(db) == before_transactions
    entries = db.query(models.JournalEntry).all()
    assert sum(row.debit for row in entries) == sum(row.credit for row in entries) == 575
    for transaction in db.query(models.Transaction):
        legs = [row for row in entries if row.transaction_id == transaction.id]
        assert sum(row.debit for row in legs) == sum(row.credit for row in legs)
    assert db.get(models.Account, account_id).is_active is True
    assert db.get(models.Capsule, capsule_id) is None


def _rule_payload(capsule_id, **changes):
    return schemas.CapsuleRuleCreate(
        capsule_id=capsule_id, trigger_type="Income", amount_value=10, **changes,
    )


def _snapshot(db):
    return {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables}


def test_delete_capsule_cascades_rules_and_holdings_but_keeps_account_without_history(db):
    capsule, cash, reserve = _capsule(db)
    capsule_id, account_id = capsule.id, reserve.id
    capsule_service.create_rule(db, 1, _rule_payload(capsule_id))
    capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=cash.id, held_amount=40))
    other, other_cash, _ = _capsule(db, client_id=2)
    other_id = other.id
    other_rule_id = capsule_service.create_rule(db, 2, _rule_payload(other_id)).id
    other_holding_id = capsule_service.create_holding(db, 2, other_id, schemas.CapsuleHoldingCreate(account_id=other_cash.id, held_amount=20)).id

    assert delete_capsule(db, 1, capsule_id)
    db.expire_all()

    assert db.query(models.CapsuleRule).filter_by(capsule_id=capsule_id).count() == 0
    assert db.query(models.CapsuleHolding).filter_by(capsule_id=capsule_id).count() == 0
    assert db.get(models.CapsuleRule, other_rule_id) is not None
    assert db.get(models.CapsuleHolding, other_holding_id) is not None
    assert db.get(models.Account, account_id).is_active is True
    assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0


def test_contribute_writes_only_holdings_neither_posted_transaction_nor_proposal_and_no_legs(db):
    capsule, cash, _ = _capsule(db)
    capsule_id, cash_id = capsule.id, cash.id
    result = capsule_workflow.contribute(db, 1, capsule_id, amount=300, from_account_id=cash_id)
    assert result == {"status": "ok", "amount": 300, "new_balance": 300}
    holding = db.query(models.CapsuleHolding).one()
    assert (holding.capsule_id, holding.account_id, holding.held_amount, holding.note) == (
        capsule_id, cash_id, 300, "Manual contribution",
    )
    # The loaded empty relationship keeps the first contribution's cache at zero.
    assert db.get(models.Capsule, capsule_id).current_balance == 0
    result = capsule_workflow.contribute(db, 1, capsule_id, amount=300, from_account_id=cash_id)
    assert result == {"status": "ok", "amount": 200, "new_balance": 500}
    assert db.get(models.Capsule, capsule_id).current_balance == 500
    result = capsule_workflow.contribute(db, 1, capsule_id, amount=10, from_account_id=cash_id)
    assert result == {
        "status": "skipped", "message": "Capsule target already reached", "amount": 0.0, "new_balance": 500,
    }
    assert db.query(models.CapsuleHolding).one().held_amount == 500
    for model in (models.Transaction, models.TransactionProposal, models.JournalEntry):
        assert db.query(model).count() == 0
    assert [calculate_account_valued_balance(db, a) for a in db.query(models.Account)] == [0, 0]


def test_rule_crud_rejects_other_clients_capsule_and_keeps_attachment_on_partial_update(db):
    capsule, cash, _ = _capsule(db)
    capsule_id = capsule.id
    other, other_cash, _ = _capsule(db, client_id=2)
    before = _snapshot(db)
    for payload, detail in [
        (_rule_payload(other.id), "Capsule not found"),
        (_rule_payload(capsule_id, source_account_id=other_cash.id), "Source account not found"),
    ]:
        with pytest.raises(NotFound) as error:
            capsule_service.create_rule(db, 1, payload)
        assert str(error.value) == detail
    assert _snapshot(db) == before
    rule = capsule_service.create_rule(db, 1, _rule_payload(capsule_id, source_account_id=cash.id))
    rule_id = rule.id
    assert capsule_service.list_rules(db, 1) == [rule]
    assert capsule_service.list_rules(db, 2) == []
    updated = capsule_service.update_rule(db, 1, rule_id, schemas.CapsuleRuleUpdate(amount_value=25, is_active=False))
    assert (updated.capsule_id, updated.amount_value, updated.is_active) == (capsule_id, 25, False)
    assert capsule_service.delete_rule(db, 1, rule_id)
    assert capsule_service.list_rules(db, 1) == []


def test_rule_update_preserves_existing_explicit_capsule_reassignment(db):
    capsule, _, _ = _capsule(db)
    rule_id = capsule_service.create_rule(db, 1, _rule_payload(capsule.id)).id
    second, _, _ = _capsule(db)
    second_id = second.id
    updated = capsule_service.update_rule(db, 1, rule_id, schemas.CapsuleRuleUpdate(capsule_id=second_id))
    assert updated.capsule_id == second_id


def test_holding_crud_replaces_existing_claim_and_leaves_current_balance_untouched(db):
    capsule, cash, _ = _capsule(db)
    capsule_id, cash_id = capsule.id, cash.id
    assert capsule_service.list_holdings(db, 1, capsule_id) == []
    holding = capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=cash_id, held_amount=800, note="first"))
    holding_id = holding.id
    assert db.get(models.Capsule, capsule_id).current_balance == 123
    replacement = capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=cash_id, held_amount=50, note="replacement"))
    assert replacement.id == holding_id
    assert (replacement.held_amount, replacement.note) == (50, "replacement")
    assert capsule_service.list_holdings(db, 1, capsule_id) == [replacement]
    updated = capsule_service.update_holding(db, 1, capsule_id, holding_id, schemas.CapsuleHoldingUpdate(held_amount=20))
    assert (updated.account_id, updated.held_amount, updated.note) == (cash_id, 20, "replacement")
    assert db.get(models.Capsule, capsule_id).current_balance == 123
    assert capsule_service.delete_holding(db, 1, capsule_id, holding_id)
    assert capsule_service.list_holdings(db, 1, capsule_id) == []
    assert db.get(models.Capsule, capsule_id).current_balance == 123
    for model in (models.Transaction, models.TransactionProposal, models.JournalEntry):
        assert db.query(model).count() == 0


def test_capsule_crud_clamps_inputs_ignores_balance_patch_and_read_commits_holdings_cache(db):
    payload = schemas.CapsuleCreate(name="Manual", target_amount=-10, monthly_contribution=-5, current_balance=999)
    capsule = capsule_service.create_capsule(db, 1, payload)
    capsule_id = capsule.id
    assert (capsule.target_amount, capsule.monthly_contribution, capsule.current_balance) == (0, 0, 0)
    cash = models.Account(client_id=1, name="Cash", account_type="asset")
    db.add(cash)
    db.commit()
    capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=cash.id, held_amount=75))
    updated = capsule_service.update_capsule(db, 1, capsule_id, schemas.CapsuleUpdate(
        target_amount=-1, monthly_contribution=None, current_balance=999,
        capsule_type=None, target_amount_source=None, monthly_contribution_source=None,
    ))
    assert (updated.target_amount, updated.monthly_contribution, updated.current_balance) == (0, 0, 75)
    assert (updated.capsule_type, updated.target_amount_source, updated.monthly_contribution_source) == ("manual", "manual", "manual")
    updated.current_balance_minor = 1
    db.commit()
    details = capsule_service.list_capsule_details(db, 1)
    assert details[0]["current_balance"] == 75
    db.rollback()
    assert db.get(models.Capsule, capsule_id).current_balance == 75
    assert capsule_service.list_capsules(db, 1, skip=1) == []
    assert capsule_service.list_capsules(db, 2) == []


def test_unknown_foreign_and_mismatched_ids_return_none_or_false_and_write_nothing(db, monkeypatch):
    capsule, cash, _ = _capsule(db)
    capsule_id = capsule.id
    rule_id = capsule_service.create_rule(db, 1, _rule_payload(capsule_id)).id
    holding_id = capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=cash.id, held_amount=20)).id
    other, _, _ = _capsule(db)
    other_id = other.id
    before = _snapshot(db)

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("Missing or foreign IDs must not flush or commit")

    monkeypatch.setattr(db, "flush", unexpected_write)
    monkeypatch.setattr(db, "commit", unexpected_write)
    for client_id, missing_capsule_id, missing_rule_id in [(1, 99999, 99999), (2, capsule_id, rule_id)]:
        assert capsule_service.update_capsule(db, client_id, missing_capsule_id, schemas.CapsuleUpdate(name="Changed")) is None
        assert capsule_service.delete_capsule(db, client_id, missing_capsule_id) is False
        assert capsule_service.update_rule(db, client_id, missing_rule_id, schemas.CapsuleRuleUpdate(amount_value=25)) is None
        assert capsule_service.delete_rule(db, client_id, missing_rule_id) is False
        assert capsule_service.update_holding(db, client_id, missing_capsule_id, holding_id, schemas.CapsuleHoldingUpdate(held_amount=25)) is None
        assert capsule_service.delete_holding(db, client_id, missing_capsule_id, holding_id) is False
    for owner_id, missing_id in [(capsule_id, 99999), (other_id, holding_id)]:
        assert capsule_service.update_holding(db, 1, owner_id, missing_id, schemas.CapsuleHoldingUpdate(held_amount=25)) is None
        assert capsule_service.delete_holding(db, 1, owner_id, missing_id) is False
    assert _snapshot(db) == before


@pytest.mark.parametrize("operation", [
    "create_capsule", "update_capsule", "delete_capsule",
    "create_rule", "update_rule", "delete_rule",
    "create_holding", "replace_holding", "update_holding", "delete_holding",
    "list_capsule_details", "contribute", "create_product_reserve_pools",
    "sync_product_reserves", "create_goal_capsule",
])
def test_commit_false_leaves_every_new_writing_function_rollbackable(db, monkeypatch, operation):
    capsule, cash, _ = _capsule(db)
    capsule_id, cash_id = capsule.id, cash.id
    rule_id = capsule_service.create_rule(db, 1, _rule_payload(capsule_id)).id
    holding_id = capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=cash_id, held_amount=20)).id
    goal = models.LifeEvent(client_id=1, name="Goal", target_date=date(2027, 12, 31), target_amount_minor=to_minor(200, "JPY"))
    product = models.Product(
        client_id=1, name="Item", funding_capsule_id=capsule_id,
        budget_treatment="reserve_allocation", is_asset=False,
        last_unit_price_minor=to_minor(100, "JPY"), frequency_days=60,
    )
    db.add_all([goal, product])
    db.commit()
    goal_id = goal.id
    before = _snapshot(db)

    def unexpected_commit(*_args, **_kwargs):
        pytest.fail("Caller owns commit and cache invalidation")

    monkeypatch.setattr(db, "commit", unexpected_commit)
    monkeypatch.setattr(capsule_service, "invalidate_client", unexpected_commit)
    monkeypatch.setattr(capsule_workflow, "invalidate_client", unexpected_commit)
    operations = {
        "create_capsule": lambda: capsule_service.create_capsule(db, 1, schemas.CapsuleCreate(name="New", target_amount=10, monthly_contribution=1), commit=False),
        "update_capsule": lambda: capsule_service.update_capsule(db, 1, capsule_id, schemas.CapsuleUpdate(name="Changed"), commit=False),
        "delete_capsule": lambda: capsule_service.delete_capsule(db, 1, capsule_id, commit=False),
        "create_rule": lambda: capsule_service.create_rule(db, 1, _rule_payload(capsule_id), commit=False),
        "update_rule": lambda: capsule_service.update_rule(db, 1, rule_id, schemas.CapsuleRuleUpdate(amount_value=25), commit=False),
        "delete_rule": lambda: capsule_service.delete_rule(db, 1, rule_id, commit=False),
        "create_holding": lambda: capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=capsule.account_id, held_amount=25), commit=False),
        "replace_holding": lambda: capsule_service.create_holding(db, 1, capsule_id, schemas.CapsuleHoldingCreate(account_id=cash_id, held_amount=25), commit=False),
        "update_holding": lambda: capsule_service.update_holding(db, 1, capsule_id, holding_id, schemas.CapsuleHoldingUpdate(held_amount=25), commit=False),
        "delete_holding": lambda: capsule_service.delete_holding(db, 1, capsule_id, holding_id, commit=False),
        "list_capsule_details": lambda: capsule_service.list_capsule_details(db, 1, commit=False),
        "contribute": lambda: capsule_workflow.contribute(db, 1, capsule_id, amount=25, from_account_id=cash_id, commit=False),
        "create_product_reserve_pools": lambda: capsule_workflow.create_product_reserve_pools(db, 1, commit=False),
        "sync_product_reserves": lambda: capsule_workflow.sync_product_reserves(db, 1, commit=False),
        "create_goal_capsule": lambda: capsule_workflow.create_goal_capsule(db, 1, goal_id, commit=False),
    }
    if operation == "delete_capsule":
        product.funding_capsule_id = None
        db.flush()
    assert operations[operation]() is not None
    db.flush()
    assert _snapshot(db) != before
    db.rollback()
    assert _snapshot(db) == before


@pytest.mark.parametrize("method", ["read", "create", "update", "delete"])
def test_holding_http_errors_keep_capsule_and_holding_not_found_distinct(db, method):
    capsule, cash, _ = _capsule(db)
    client = db.get(models.Client, 1)
    calls = {
        "read": lambda capsule_id: capsule_router.read_capsule_holdings(capsule_id, db=db, current_client=client),
        "create": lambda capsule_id: capsule_router.create_capsule_holding(capsule_id, schemas.CapsuleHoldingCreate(account_id=cash.id, held_amount=10), db=db, current_client=client),
        "update": lambda capsule_id: capsule_router.update_capsule_holding(capsule_id, 99999, schemas.CapsuleHoldingUpdate(held_amount=10), db=db, current_client=client),
        "delete": lambda capsule_id: capsule_router.delete_capsule_holding(capsule_id, 99999, db=db, current_client=client),
    }
    error_type = NotFound if method == "create" else HTTPException
    with pytest.raises(error_type) as error:
        calls[method](99999)
    if method == "create":
        assert str(error.value) == "Capsule not found"
    else:
        assert (error.value.status_code, error.value.detail) == (404, "Capsule not found")
    if method in {"update", "delete"}:
        with pytest.raises(HTTPException) as error:
            calls[method](capsule.id)
        assert (error.value.status_code, error.value.detail) == (404, "Holding not found")
