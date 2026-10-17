"""Archive choices preserve history and release attributed claims atomically."""
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from scenario_fixtures import goal_scenario_id

from app import models, schemas
from app.database import Base
from app.domain.errors import NotFound, Refused
from app.domain.journal import Leg
from app.routers.life_events import archive_life_event
from app.services import capsule_service, goal_service, ledger_service, strategy_service


@pytest.fixture
def workspace():
    engine = create_engine('sqlite://')

    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        client = models.Client(name='Archive choices', general_settings={'currency': 'JPY'}, ai_config={})
        other = models.Client(name='Other', general_settings={'currency': 'JPY'}, ai_config={})
        db.add_all([client, other])
        db.flush()
        goal = models.LifeEvent(scenario_id=goal_scenario_id(db, client.id), client_id=client.id, name='Home', target_date=date(2028, 12, 31), target_amount_minor=2000)
        source = models.Account(client_id=client.id, name='Savings', account_type='asset', is_active=True)
        old_source = models.Account(client_id=client.id, name='Former source', account_type='asset', is_active=True)
        destination = models.Account(client_id=client.id, name='Cash', account_type='asset', is_active=True)
        income = models.Account(client_id=client.id, name='Income', account_type='income')
        db.add_all([goal, source, old_source, destination, income])
        db.flush()
        capsule = models.Capsule(client_id=client.id, life_event_id=goal.id, name='Home savings', target_amount_minor=2000, monthly_contribution_minor=10)
        empty = models.Capsule(client_id=client.id, life_event_id=goal.id, name='Empty', target_amount_minor=100, monthly_contribution_minor=10)
        unrelated = models.Capsule(client_id=client.id, name='Unrelated', target_amount_minor=100, monthly_contribution_minor=10)
        db.add_all([capsule, empty, unrelated])
        db.flush()
        db.add(models.CapsuleFundingSource(client_id=client.id, capsule_id=capsule.id, account_id=source.id, target_amount_minor=2000))
        for cap in [capsule, empty, unrelated]:
            db.add(models.CapsuleRule(client_id=client.id, capsule_id=cap.id, trigger_type='Transfer', amount_type='fixed', amount_minor=10, is_active=True))
        db.add(models.Milestone(client_id=client.id, life_event_id=goal.id, date=goal.target_date, target_amount_minor=2000))
        # A claim on an account removed from the funding plan is still real money.
        for account, currency, minor in [(source, 'JPY', 500), (old_source, 'JPY', 200), (old_source, 'USD', 125)]:
            ledger_service.create_transaction(db, client_id=client.id, date=date(2026, 10, 14), description='Saved', amount_minor=minor, currency=currency, legs=[Leg(account.id, debit=minor, capsule_id=capsule.id), Leg(income.id, credit=minor)])
        db.commit()
        yield db, client, other, goal, capsule, empty, unrelated, source, destination
    engine.dispose()


def client_currency_claims_only(db):
    foreign = db.query(models.Transaction).filter_by(currency='USD').one()
    db.query(models.JournalEntry).filter_by(transaction_id=foreign.id).delete()
    db.delete(foreign)
    db.commit()


def journal_rows(db):
    return db.execute(models.JournalEntry.__table__.select()).all()


def test_keep_is_default_and_preserves_every_related_row(workspace):
    db, client, _, goal, capsule, *_ = workspace
    before = {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables if table.name != 'life_events'}
    archived = archive_life_event(goal.id, db=db, current_client=client)
    assert archived.archived_at is not None
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 700, 'USD': 125}
    assert {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables if table.name != 'life_events'} == before


def test_stop_rules_leaves_claims_money_and_history_alone(workspace):
    db, client, _, goal, capsule, empty, unrelated, *_ = workspace
    before = journal_rows(db)
    response = archive_life_event(goal.id, schemas.GoalArchiveRequest(capsule_action='stop_rules'), db=db, current_client=client)
    assert response.archived_at is not None
    rules = {row.capsule_id: row.is_active for row in db.query(models.CapsuleRule)}
    assert rules == {capsule.id: False, empty.id: False, unrelated.id: True}
    assert journal_rows(db) == before
    assert db.query(models.Transaction).count() == 3
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 700, 'USD': 125}
    goal_service.unarchive_goal(db, client.id, goal.id)
    assert db.query(models.CapsuleRule).filter_by(capsule_id=capsule.id).one().is_active is False
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 700, 'USD': 125}


def test_release_returns_client_currency_from_actual_claim_accounts(workspace):
    db, client, _, goal, capsule, _, _, source, destination = workspace
    client_currency_claims_only(db)
    before = journal_rows(db)
    archive_life_event(goal.id, schemas.GoalArchiveRequest(capsule_action='release', transfer_account_id=destination.id), db=db, current_client=client)
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {}
    assert db.query(models.Transaction).count() == 4
    assert journal_rows(db)[:len(before)] == before
    released = db.query(models.Transaction).filter(models.Transaction.description.like('Goal archived%')).all()
    assert sorted((row.currency, row.amount_minor) for row in released) == [('JPY', 200), ('JPY', 500)]
    for tx in released:
        legs = db.query(models.JournalEntry).filter_by(transaction_id=tx.id).all()
        assert sum(row.debit_minor for row in legs) == sum(row.credit_minor for row in legs) == tx.amount_minor
        assert next(row for row in legs if row.credit_minor).capsule_id == capsule.id
        assert next(row for row in legs if row.debit_minor).account_id == destination.id
        assert next(row for row in legs if row.debit_minor).capsule_id is None
    assert db.get(models.Account, source.id).is_active is True
    assert db.query(models.Capsule).count() == 3
    assert db.query(models.Milestone).count() == 1
    assert all(row.is_active for row in db.query(models.CapsuleRule))
    goal_service.unarchive_goal(db, client.id, goal.id)
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {}
    assert db.query(models.Transaction).count() == 4


def test_release_repeated_without_new_claims_moves_nothing(workspace):
    db, client, _, goal, _, _, _, _, destination = workspace
    client_currency_claims_only(db)
    goal_service.archive_goal(db, client.id, goal.id, capsule_action='release', transfer_account_id=destination.id)
    stamp = goal.archived_at
    goal_service.archive_goal(db, client.id, goal.id, capsule_action='release', transfer_account_id=destination.id)
    assert goal.archived_at == stamp
    assert db.query(models.Transaction).count() == 4


@pytest.mark.parametrize('empty', [False, True])
def test_release_refuses_without_destination_even_if_empty(workspace, empty):
    db, client, _, goal, *_ = workspace
    if empty:
        goal = models.LifeEvent(scenario_id=goal_scenario_id(db, client.id), client_id=client.id, name='Empty goal', target_date=date(2028, 1, 1), target_amount_minor=0)
        db.add(goal)
        db.commit()
    before = journal_rows(db)
    with pytest.raises(Refused, match='transfer_account_id is required') as failure:
        archive_life_event(goal.id, schemas.GoalArchiveRequest(capsule_action='release'), db=db, current_client=client)
    assert failure.value.status_code == 422
    assert goal.archived_at is None
    assert journal_rows(db) == before


@pytest.mark.parametrize('kind', ['foreign', 'missing', 'inactive', 'expense'])
def test_release_rejects_unusable_destination_without_changes(workspace, kind):
    db, client, other, goal, *_ = workspace
    destination = models.Account(client_id=other.id if kind == 'foreign' else client.id, name=kind, account_type='expense' if kind == 'expense' else 'asset', is_active=kind != 'inactive')
    db.add(destination)
    db.commit()
    before = journal_rows(db)
    with pytest.raises((NotFound, Refused)):
        goal_service.archive_goal(db, client.id, goal.id, capsule_action='release', transfer_account_id=999999 if kind == 'missing' else destination.id)
    assert goal.archived_at is None
    assert journal_rows(db) == before


@pytest.mark.parametrize('action', ['stop_rules', 'release', 'detach'])
def test_capsule_decision_can_rollback_with_callers_transaction(workspace, action):
    db, client, _, goal, capsule, _, _, _, destination = workspace
    if action == 'release':
        client_currency_claims_only(db)
    before = journal_rows(db)
    goal_service.archive_goal(db, client.id, goal.id, capsule_action=action, transfer_account_id=destination.id, commit=False)
    assert goal.archived_at is not None
    db.rollback()
    assert goal.archived_at is None
    assert journal_rows(db) == before
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == ({'JPY': 700} if action == 'release' else {'JPY': 700, 'USD': 125})
    assert capsule.life_event_id == goal.id
    assert all(row.is_active for row in db.query(models.CapsuleRule))


def test_posting_failure_rolls_back_earlier_release_and_archive(workspace, monkeypatch):
    db, client, _, goal, capsule, _, _, _, destination = workspace
    client_currency_claims_only(db)
    before = journal_rows(db)
    post = goal_service.create_transaction
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('Posting failed')
        return post(*args, **kwargs)

    monkeypatch.setattr(goal_service, 'create_transaction', fail_second)
    with pytest.raises(RuntimeError, match='Posting failed'):
        goal_service.archive_goal(db, client.id, goal.id, capsule_action='release', transfer_account_id=destination.id)
    assert goal.archived_at is None
    assert journal_rows(db) == before
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 700}


def test_release_to_source_unearmarks_without_changing_its_own_money(workspace):
    db, client, _, goal, capsule, _, _, source, _ = workspace
    client_currency_claims_only(db)
    goal_service.archive_goal(db, client.id, goal.id, capsule_action='release', transfer_account_id=source.id)
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {}
    entries = db.query(models.JournalEntry).filter_by(account_id=source.id).join(models.Transaction).filter(models.Transaction.currency == 'JPY').all()
    # The source's own 500 yen is unearmarked; the other account's 200 yen arrives.
    assert sum(row.debit_minor - row.credit_minor for row in entries) == 700


def test_goal_capsules_expose_claims_separately_by_currency(workspace):
    db, client, _, goal, capsule, *_ = workspace
    result = goal_service.list_goal_capsules(db, client.id, goal.id)
    row = next(row for row in result if row['id'] == capsule.id)
    assert row['current_balance'] == 700
    assert row['claims'] == [{'currency': 'JPY', 'amount_minor': 700, 'amount': 700.0}, {'currency': 'USD', 'amount_minor': 125, 'amount': 1.25}]


def test_archive_payload_rejects_unknown_choice():
    with pytest.raises(ValidationError):
        schemas.GoalArchiveRequest(capsule_action='discard')


def test_roadmap_can_project_archived_goal_with_monthly_plan(workspace):
    db, client, _, goal, *_ = workspace
    goal_service.archive_goal(db, client.id, goal.id)
    roadmap = strategy_service.get_roadmap_projection(db, client.id, years=1, roadmap_interval='monthly', include_archived=True)
    projected = next(row for row in roadmap['events'] if row['id'] == goal.id)
    assert projected['archived_at']
    assert projected['roadmap'][1]['label'].count('-') == 1
    assert roadmap['params']['reference_date'] == date.today().isoformat()
    assert roadmap['milestones'][0]['life_event_id'] == goal.id
    assert strategy_service.get_roadmap_projection(db, client.id, years=1)['events'] == []


def test_detach_keeps_capsules_rules_money_and_history(workspace):
    db, client, _, goal, capsule, empty, unrelated, *_ = workspace
    before = {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables if table.name not in {'life_events', 'capsules'}}
    result = archive_life_event(goal.id, schemas.GoalArchiveRequest(capsule_action='detach'), db=db, current_client=client)
    assert result.archived_at is not None
    assert capsule.life_event_id is None
    assert empty.life_event_id is None
    assert unrelated.life_event_id is None
    assert db.query(models.Capsule).count() == 3
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 700, 'USD': 125}
    assert {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables if table.name not in {'life_events', 'capsules'}} == before
    goal_service.unarchive_goal(db, client.id, goal.id)
    assert capsule.life_event_id is None
    assert goal.capsules == []


@pytest.mark.parametrize('commit', [True, False])
def test_release_refuses_foreign_claim_before_any_posting(workspace, commit):
    db, client, _, goal, capsule, _, _, _, destination = workspace
    before = journal_rows(db)
    with pytest.raises(Refused) as failure:
        goal_service.archive_goal(db, client.id, goal.id, capsule_action='release', transfer_account_id=destination.id, commit=commit)
    assert failure.value.status_code == 422
    assert capsule.name in str(failure.value)
    assert 'USD' in str(failure.value)
    assert '紐づけを解除' in str(failure.value)
    assert 'USD の口座' in str(failure.value)
    assert goal.archived_at is None
    assert journal_rows(db) == before
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 700, 'USD': 125}
