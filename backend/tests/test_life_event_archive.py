"""A called-off goal is a reversible fact, never a request to return savings."""
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.journal import Leg
from app.domain.transfer import EXPORT_VERSION
from app.routers.life_events import router
from app.services import capsule_service, goal_service, ledger_service
from app.services.data_transfer_service import export_client, import_client


@pytest.fixture
def workspace():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)

    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as db:
        client = models.Client(name='Archive test', general_settings={'currency': 'JPY'}, ai_config={})
        db.add(client)
        db.flush()
        goal = models.LifeEvent(client_id=client.id, name='House', target_date=date(2027, 12, 31), target_amount_minor=1000)
        account = models.Account(client_id=client.id, name='Savings', account_type='asset')
        income = models.Account(client_id=client.id, name='Income', account_type='income')
        dest = models.Account(client_id=client.id, name='Cash', account_type='asset')
        db.add_all([goal, account, income, dest])
        db.flush()
        capsule = models.Capsule(client_id=client.id, life_event_id=goal.id, name='House savings', target_amount_minor=1000, monthly_contribution_minor=10)
        db.add(capsule)
        db.flush()
        db.add_all([
            models.CapsuleFundingSource(client_id=client.id, capsule_id=capsule.id, account_id=account.id, target_amount_minor=1000),
            models.CapsuleRule(client_id=client.id, capsule_id=capsule.id, trigger_type='Income', amount_type='fixed', amount_minor=10),
            models.Milestone(client_id=client.id, life_event_id=goal.id, date=goal.target_date, target_amount_minor=1000),
        ])
        ledger_service.create_transaction(db, client_id=client.id, date=date(2026, 10, 14), description='Saved', amount_minor=500, currency='JPY', legs=[Leg(account.id, debit=500, capsule_id=capsule.id), Leg(income.id, credit=500)])
        db.commit()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_client] = lambda: client
        with TestClient(app) as http:
            yield db, http, client, goal, capsule, account, dest
    engine.dispose()


def _rows(db):
    # Every table besides the goal must remain byte-for-byte equivalent.
    return {table.name: db.execute(table.select()).all() for table in Base.metadata.sorted_tables if table.name != 'life_events'}


def test_archive_hides_both_listings_and_restore_is_reversible(workspace):
    db, http, client, goal, capsule, account, _ = workspace
    before = _rows(db)
    response = http.post(f'/life-events/{goal.id}/archive')
    assert response.status_code == 200
    stamp = response.json()['archived_at']
    assert datetime.fromisoformat(stamp)
    for path in ['/life-events/', '/life-events/with-progress']:
        assert http.get(path).json() == []
        included = http.get(path, params={'include_archived': True}).json()
        assert len(included) == 1
        assert included[0]['archived_at'] == stamp
    assert _rows(db) == before
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 500}
    assert db.get(models.Account, account.id).is_active is True
    # Repeating archive preserves the original fact's timestamp.
    assert http.post(f'/life-events/{goal.id}/archive').json()['archived_at'] == stamp
    assert http.post(f'/life-events/{goal.id}/unarchive').json()['archived_at'] is None
    assert http.post(f'/life-events/{goal.id}/unarchive').status_code == 200
    for path in ['/life-events/', '/life-events/with-progress']:
        assert http.get(path).json()[0]['id'] == goal.id
    assert _rows(db) == before


def test_archive_does_not_call_delete_and_delete_still_returns_money(workspace, monkeypatch):
    db, http, client, goal, capsule, _, dest = workspace
    goal_id, capsule_id, dest_id = goal.id, capsule.id, dest.id
    with monkeypatch.context() as patch:
        def unexpected(*args, **kwargs):
            pytest.fail('Archive must not enter the deletion or transfer path')
        patch.setattr(goal_service, 'delete_goal', unexpected)
        patch.setattr(goal_service, 'create_transaction', unexpected)
        patch.setattr(db, 'delete', unexpected)
        assert http.post(f'/life-events/{goal_id}/archive').status_code == 200
    assert goal_service.delete_goal(db, client.id, goal_id, transfer_account_id=dest_id)
    db.expire_all()
    assert db.get(models.LifeEvent, goal_id) is None
    assert db.get(models.Capsule, capsule_id) is None
    returned = db.query(models.JournalEntry).filter_by(account_id=dest_id).one()
    assert returned.debit_minor == 500


@pytest.mark.parametrize('action', ['archive', 'unarchive'])
def test_foreign_or_missing_goal_is_not_modified(workspace, action):
    db, http, client, goal, *_ = workspace
    before = _rows(db)
    assert http.post(f'/life-events/99999/{action}').status_code == 404
    foreign = models.Client(name='Other', general_settings={}, ai_config={})
    db.add(foreign)
    db.commit()
    app = http.app
    app.dependency_overrides[get_current_client] = lambda: foreign
    assert http.post(f'/life-events/{goal.id}/{action}').status_code == 404
    assert db.get(models.LifeEvent, goal.id).archived_at is None
    # Only the explicitly added client changed.
    assert {k: v for k, v in _rows(db).items() if k != 'clients'} == {k: v for k, v in before.items() if k != 'clients'}


@pytest.mark.parametrize('archive', [True, False])
def test_archive_service_can_participate_in_caller_transaction(workspace, archive):
    db, _, client, goal, *_ = workspace
    if not archive:
        goal_service.archive_goal(db, client.id, goal.id)
    stamp = goal.archived_at
    action = goal_service.archive_goal if archive else goal_service.unarchive_goal
    action(db, client.id, goal.id, commit=False)
    assert bool(goal.archived_at) is archive
    db.rollback()
    assert goal.archived_at == stamp


def test_backup_round_trip_preserves_archive_and_v12_defaults_to_active(workspace):
    db, _, client, goal, *_ = workspace
    goal_service.archive_goal(db, client.id, goal.id)
    document = export_client(db, client)
    assert document['version'] == EXPORT_VERSION == 20
    assert document['data']['life_events'][0]['archived_at'] == goal.archived_at.isoformat()
    target = models.Client(name='Restore', general_settings={'currency': 'JPY'}, ai_config={})
    db.add(target)
    db.commit()
    import_client(db, target, data=document['data'], version=document['version'], manifest=document['manifest'])
    restored = goal_service.list_goals(db, target.id, include_archived=True)[0]
    assert restored.archived_at == goal.archived_at
    assert capsule_service.claimed_minor(db, target.id, restored.capsules[0].id) == {'JPY': 500}
    document['data']['life_events'][0].pop('archived_at')
    legacy = models.Client(name='Legacy', general_settings={'currency': 'JPY'}, ai_config={})
    db.add(legacy)
    db.commit()
    import_client(db, legacy, data=document['data'], version=12, manifest=None)
    assert goal_service.list_goals(db, legacy.id)[0].archived_at is None


def test_archive_preserves_claims_in_each_currency(workspace):
    db, http, client, goal, capsule, account, _ = workspace
    income = db.query(models.Account).filter_by(client_id=client.id, account_type='income').one()
    ledger_service.create_transaction(db, client_id=client.id, date=date(2026, 10, 14), description='Foreign savings', amount_minor=125, currency='USD', legs=[Leg(account.id, debit=125, capsule_id=capsule.id), Leg(income.id, credit=125)])
    db.commit()
    before = _rows(db)
    assert http.post(f'/life-events/{goal.id}/archive').status_code == 200
    assert capsule_service.claimed_minor(db, client.id, capsule.id) == {'JPY': 500, 'USD': 125}
    assert _rows(db) == before


def test_called_off_goal_is_excluded_from_savings_allocation_and_future_demand(workspace):
    from app.services import strategy_service

    db, _, client, goal, *_ = workspace
    active = models.LifeEvent(client_id=client.id, name='Active', priority=2, target_date=goal.target_date, target_amount_minor=2000)
    db.add(active)
    db.commit()
    goal_service.archive_goal(db, client.id, goal.id)
    context = strategy_service.get_goal_simulation_context(db, client.id, active, monthly_savings=100)
    assert context['allocated_monthly_savings'] == 100
    archived_context = strategy_service.get_goal_simulation_context(db, client.id, goal, monthly_savings=100)
    assert archived_context['allocated_monthly_savings'] == 0
    assert strategy_service.aggregate_life_event_demand_by_year(db, client.id, years=2)[-1]['event_count'] == 1
    assert len(strategy_service.generate_budget_from_goals(db, '2026-10', client.id)) == 1
