from scenario_fixtures import goal_scenario_id

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
            models.Client(id=1, name="Capsule CRUD", general_settings={}),
            models.Client(id=2, name="Other client", general_settings={}),
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
        client_id=client_id, name="Savings", funding_sources=[models.CapsuleFundingSource(client_id=client_id, account_id=reserve.id, target_amount_minor=to_minor(500, "JPY") or 0)],
        target_amount_minor=to_minor(500, "JPY"), monthly_contribution_minor=to_minor(10, "JPY"),
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


def test_delete_capsule_cascades_rules_and_plan_but_keeps_account_without_history(db):
    capsule, cash, reserve = _capsule(db)
    capsule_id, account_id = capsule.id, reserve.id
    capsule_service.create_rule(db, 1, _rule_payload(capsule_id))
    other, other_cash, _ = _capsule(db, client_id=2)
    other_id = other.id
    other_rule_id = capsule_service.create_rule(db, 2, _rule_payload(other_id)).id
    other_source_id = other.funding_sources[0].id

    deleted = delete_capsule(db, 1, capsule_id)
    db.expire_all()

    # X7: the account the capsule reserved into is reported, not emptied.
    assert (deleted.capsule_id, deleted.rules_deleted) == (capsule_id, 1)
    assert (deleted.retained_account_id, deleted.retained_account_name) == (account_id, reserve.name)
    assert db.query(models.CapsuleRule).filter_by(capsule_id=capsule_id).count() == 0
    assert db.get(models.CapsuleRule, other_rule_id) is not None
    assert db.query(models.CapsuleFundingSource).filter_by(capsule_id=capsule_id).count() == 0
    assert db.get(models.CapsuleFundingSource, other_source_id) is not None
    assert db.get(models.Account, account_id).is_active is True
    assert db.query(models.Transaction).count() == db.query(models.JournalEntry).count() == 0


def test_contribute_posts_attributed_transfers_and_clamps(db):
    capsule, cash, reserve = _capsule(db)
    capsule_id, cash_id = capsule.id, cash.id
    result = capsule_workflow.contribute(db, 1, capsule_id, amount=300, from_account_id=cash_id)
    assert result == {"status": "ok", "amount": 300, "new_balance": 300}
    result = capsule_workflow.contribute(db, 1, capsule_id, amount=300, from_account_id=cash_id)
    assert result == {"status": "ok", "amount": 200, "new_balance": 500}
    assert capsule_workflow.contribute(db, 1, capsule_id, amount=10, from_account_id=cash_id) == {
        "status": "skipped", "message": "Capsule target already reached", "amount": 0.0, "new_balance": 500,
    }
    assert db.query(models.TransactionProposal).count() == 0
    assert db.query(models.Transaction).count() == 2
    assert db.query(models.JournalEntry).count() == 4
    for leg in db.query(models.JournalEntry):
        assert leg.capsule_id == (capsule_id if leg.account_id == reserve.id else None)
    assert calculate_account_valued_balance(db, cash) == -500
    assert calculate_account_valued_balance(db, reserve) == 500


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


def test_capsule_crud_clamps_inputs_and_ignores_retired_balance_input(db):
    payload = schemas.CapsuleCreate(name="Manual", target_amount=-10, monthly_contribution=-5, current_balance=999)
    capsule = capsule_service.create_capsule(db, 1, payload)
    capsule_id = capsule.id
    assert (capsule.target_amount, capsule.monthly_contribution, capsule_service.capsule_balance(db, capsule)) == (0, 0, 0)
    cash = models.Account(client_id=1, name="Cash", account_type="asset")
    db.add(cash)
    db.commit()
    updated = capsule_service.update_capsule(db, 1, capsule_id, schemas.CapsuleUpdate(
        target_amount=-1, monthly_contribution=None, current_balance=999,
        capsule_type=None, target_amount_source=None, monthly_contribution_source=None,
    ))
    assert (updated.target_amount, updated.monthly_contribution, capsule_service.capsule_balance(db, updated)) == (0, 0, 0)
    for model in (models.Transaction, models.TransactionProposal, models.JournalEntry):
        assert db.query(model).count() == 0
    assert (updated.capsule_type, updated.target_amount_source, updated.monthly_contribution_source) == ("manual", "manual", "manual")
    db.commit()
    details = capsule_service.list_capsule_details(db, 1)
    assert details[0]["current_balance"] == 0
    assert not db.new and not db.dirty and not db.deleted
    db.rollback()
    assert capsule_service.capsule_balance(db, db.get(models.Capsule, capsule_id)) == 0
    assert capsule_service.list_capsules(db, 1, skip=1) == []
    assert capsule_service.list_capsules(db, 2) == []


def test_unknown_foreign_and_mismatched_ids_return_none_or_false_and_write_nothing(db, monkeypatch):
    capsule, cash, _ = _capsule(db)
    capsule_id = capsule.id
    rule_id = capsule_service.create_rule(db, 1, _rule_payload(capsule_id)).id
    other, _, _ = _capsule(db)
    other_id = other.id
    before = _snapshot(db)

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("Missing or foreign IDs must not flush or commit")

    monkeypatch.setattr(db, "flush", unexpected_write)
    monkeypatch.setattr(db, "commit", unexpected_write)
    for client_id, missing_capsule_id, missing_rule_id in [(1, 99999, 99999), (2, capsule_id, rule_id)]:
        assert capsule_service.update_capsule(db, client_id, missing_capsule_id, schemas.CapsuleUpdate(name="Changed")) is None
        assert capsule_service.delete_capsule(db, client_id, missing_capsule_id) is None
        assert capsule_service.update_rule(db, client_id, missing_rule_id, schemas.CapsuleRuleUpdate(amount_value=25)) is None
        assert capsule_service.delete_rule(db, client_id, missing_rule_id) is False
    assert _snapshot(db) == before


@pytest.mark.parametrize("operation", [
    "create_capsule", "update_capsule", "delete_capsule",
    "create_rule", "update_rule", "delete_rule",
    "contribute", "create_goal_capsule",
])
def test_commit_false_leaves_every_new_writing_function_rollbackable(db, monkeypatch, operation):
    capsule, cash, _ = _capsule(db)
    capsule_id, cash_id = capsule.id, cash.id
    rule_id = capsule_service.create_rule(db, 1, _rule_payload(capsule_id)).id
    goal = models.LifeEvent(scenario_id=goal_scenario_id(db, 1), client_id=1, name="Goal", target_date=date(2027, 12, 31), target_amount_minor=to_minor(200, "JPY"))
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
        "contribute": lambda: capsule_workflow.contribute(db, 1, capsule_id, amount=25, from_account_id=cash_id, commit=False),
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


def test_list_capsule_details_neither_flushes_nor_commits(db, monkeypatch):
    capsule, cash, _ = _capsule(db)
    before = _snapshot(db)

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("Serializing capsules must not persist anything")

    monkeypatch.setattr(db, "commit", unexpected_write)
    monkeypatch.setattr(db, "flush", unexpected_write)
    assert capsule_service.list_capsule_details(db, 1)[0]["current_balance"] == 0
    assert not db.new and not db.dirty and not db.deleted
    assert _snapshot(db) == before


def test_deleting_a_capsule_leaves_its_account_and_balance_alone(db):
    """X7: a capsule owns the reservation, not the money.

    DELETE used to accept a transfer_account_id and ignore it, so the same
    argument meant "where to return the balance" on goal deletion and nothing
    here. Deleting a goal deletes its capsules' accounts, which is why the
    balance has to move first. Deleting a capsule leaves the account standing,
    so there is nothing to return.
    """
    capsule, cash, reserve = _capsule(db)
    capsule_id, account_id = capsule.id, reserve.id
    currency = get_client_currency(db, 1)
    ledger_service.create_transaction(
        db, client_id=1, date=date.today(), description="Reserved",
        amount_minor=Money.from_major("5000", currency).minor, currency=currency,
        from_account_id=cash.id, to_account_id=reserve.id,
    )
    db.commit()
    assert calculate_account_valued_balance(db, reserve) == 5000

    deleted = delete_capsule(db, 1, capsule_id)
    db.expire_all()

    assert db.get(models.Capsule, capsule_id) is None
    account = db.get(models.Account, account_id)
    assert account is not None and account.is_active is True
    assert calculate_account_valued_balance(db, account) == 5000
    assert (deleted.retained_account_id, deleted.retained_account_name) == (account_id, account.name)
    # No transfer was invented to move the money anywhere.
    assert db.query(models.Transaction).count() == 1


def test_deleting_a_capsule_with_no_account_reports_none(db):
    capsule = models.Capsule(client_id=1, name="Unbound", target_amount_minor=to_minor(100, "JPY"),
                             monthly_contribution_minor=0)
    db.add(capsule)
    db.commit()
    deleted = delete_capsule(db, 1, capsule.id)
    assert (deleted.retained_account_id, deleted.retained_account_name) == (None, None)
    assert deleted.rules_deleted == 0
