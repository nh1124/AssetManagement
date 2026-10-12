from app.services.money_storage import to_minor, rule_amount_fields

from backend.app.domain.money import Money
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.services import goal_service, ledger_service
from app.services.fx_service import get_client_currency
from app.workflows.goal_workflow import create_goal


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add(models.Client(id=1, name="Goal CRUD", general_settings={}, ai_config={}))
        session.commit()
        yield session
    engine.dispose()


def _goal_with_capsule_account(db):
    goal = models.LifeEvent(
        client_id=1, name="Emergency fund", target_date=date(2027, 12, 31),
        target_amount_minor=to_minor(500, "JPY"), priority=1,
    )
    earmarked = models.Account(client_id=1, name="Goal funds", account_type="asset")
    income = models.Account(client_id=1, name="Income", account_type="income")
    db.add_all([goal, earmarked, income])
    db.flush()
    capsule = models.Capsule(
        client_id=1, life_event_id=goal.id, account_id=earmarked.id,
        name=goal.name, target_amount_minor=to_minor(500, "JPY"), monthly_contribution_minor=to_minor(0, "JPY"),
    )
    db.add(capsule)
    db.flush()
    db.add_all([
        models.CapsuleRule(
            client_id=1, capsule_id=capsule.id, trigger_type="Transfer",
            amount_type="fixed", **rule_amount_fields(10, "fixed", "JPY"),
        ),
        models.Milestone(client_id=1, life_event_id=goal.id, date=goal.target_date, target_amount_minor=to_minor(500, "JPY")),
    ])
    db.commit()
    return goal.id, capsule.id, earmarked.id, income.id


def _journal_rows(db):
    return [
        (row.id, row.transaction_id, row.account_id, row.debit, row.credit)
        for row in db.query(models.JournalEntry).order_by(models.JournalEntry.id)
    ]


def test_delete_goal_preserves_every_ledger_leg_and_transaction_and_balances_books(db):
    goal_id, capsule_id, account_id, income_id = _goal_with_capsule_account(db)
    currency = get_client_currency(db, 1)
    ledger_service.create_transaction(
        db, client_id=1, date=date(2026, 10, 11), description="Fund goal",
        amount_minor=Money.from_major(str(500), currency).minor, currency=currency,
        from_account_id=income_id, to_account_id=account_id,
    )
    db.commit()
    # Zero holdings must not be mistaken for an account without journal history.
    assert db.query(models.CapsuleHolding).count() == 0
    before_entries = _journal_rows(db)
    before_transactions = [
        (row.id, row.client_id, row.date, row.description, row.amount, row.currency)
        for row in db.query(models.Transaction).order_by(models.Transaction.id)
    ]
    assert len(before_entries) == 2

    assert goal_service.delete_goal(db, 1, goal_id)
    db.expire_all()

    assert _journal_rows(db) == before_entries
    assert [
        (row.id, row.client_id, row.date, row.description, row.amount, row.currency)
        for row in db.query(models.Transaction).order_by(models.Transaction.id)
    ] == before_transactions
    entries = db.query(models.JournalEntry).all()
    assert sum(row.debit for row in entries) == sum(row.credit for row in entries) == 500
    for transaction in db.query(models.Transaction):
        legs = [row for row in entries if row.transaction_id == transaction.id]
        assert sum(row.debit for row in legs) == sum(row.credit for row in legs)
    assert db.get(models.Account, account_id).is_active is False
    assert db.get(models.LifeEvent, goal_id) is None
    assert db.get(models.Capsule, capsule_id) is None
    assert db.query(models.CapsuleRule).count() == 0
    assert db.query(models.Milestone).count() == 0


def test_delete_goal_deletes_earmarked_account_without_journal_history(db):
    goal_id, capsule_id, account_id, income_id = _goal_with_capsule_account(db)
    assert goal_service.delete_goal(db, 1, goal_id)
    db.expire_all()
    assert db.get(models.LifeEvent, goal_id) is None
    assert db.get(models.Capsule, capsule_id) is None
    assert db.get(models.Account, account_id) is None
    assert db.get(models.Account, income_id) is not None
    assert db.query(models.JournalEntry).count() == 0
    assert db.query(models.Transaction).count() == 0


def test_update_and_delete_unknown_or_foreign_goal_write_nothing(db, monkeypatch):
    goal_id, _, _, _ = _goal_with_capsule_account(db)
    before = {
        table.name: db.execute(table.select()).all()
        for table in Base.metadata.sorted_tables
    }

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("Missing goal must not flush or commit")

    monkeypatch.setattr(db, "commit", unexpected_write)
    monkeypatch.setattr(db, "flush", unexpected_write)
    for client_id, missing_id in [(1, 99999), (2, goal_id)]:
        assert goal_service.update_goal(db, client_id, missing_id, schemas.LifeEventUpdate(name="Changed")) is None
        assert goal_service.delete_goal(db, client_id, missing_id) is False
    assert {
        table.name: db.execute(table.select()).all()
        for table in Base.metadata.sorted_tables
    } == before


@pytest.mark.parametrize("commit", [True, False])
def test_create_goal_writes_one_goal_annual_milestones_and_one_capsule_without_accounts_or_ledger(db, monkeypatch, commit):
    from app.services.milestone_service import build_default_milestone_rows

    commits = []
    original_commit = db.commit

    def record_commit():
        original_commit()
        commits.append(tuple(db.query(model).count() for model in (
            models.LifeEvent, models.Milestone, models.Capsule,
        )))

    monkeypatch.setattr(db, "commit", record_commit)
    payload = schemas.LifeEventCreate(
        name="Emergency fund", target_date=date(2027, 12, 31), target_amount=500, priority=1,
    )
    goal = create_goal(db, 1, payload, commit=commit)
    assert goal_service.list_goals(db, 1) == [goal]
    assert goal_service.list_goals(db, 2) == []
    capsule = db.query(models.Capsule).one()
    assert (capsule.client_id, capsule.life_event_id, capsule.account_id) == (1, goal.id, None)
    assert (capsule.name, capsule.target_amount, capsule.monthly_contribution) == (payload.name, 500, 0)
    assert (capsule.capsule_type, capsule.target_amount_source) == ("life_event", "life_event")
    expected_rows = build_default_milestone_rows(db, 1, goal.id)
    milestones = db.query(models.Milestone).order_by(models.Milestone.date).all()
    assert len(milestones) == len(expected_rows) > 0
    assert [(m.date, m.target_amount, m.note, m.source, m.source_snapshot) for m in milestones] == [
        (row["date"], Money.from_major(str(row["target_amount"]), get_client_currency(db, 1)).to_float(), row["note"], row["source"], row["source_snapshot"])
        for row in sorted(expected_rows, key=lambda row: row["date"])
    ]
    for model in (models.Account, models.Transaction, models.JournalEntry, models.CapsuleHolding, models.CapsuleRule):
        assert db.query(model).count() == 0
    if commit:
        assert commits == [(1, 0, 0), (1, len(milestones), 0), (1, len(milestones), 1)]
    else:
        assert commits == []
        db.rollback()
        for model in (models.LifeEvent, models.Milestone, models.Capsule):
            assert db.query(model).count() == 0
