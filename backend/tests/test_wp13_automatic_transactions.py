from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from pathlib import Path
import importlib.util

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Invalid
from app.domain.automatic_migration import migrate_automatic_data, REMOVED_FIELDS
from app.services import automatic_recording_service as recording, registry_service as registry, ledger_service
from app.services.schedule_rules import occurrences, next_occurrence
from app.workflows import automatic_recording_workflow as workflow
from app.routers import registry_entries, automatic_recordings


def schedule(**changes):
    return SimpleNamespace(**{**dict(start_date=date(2024, 1, 31), end_date=None, repeat_mode='indefinite',
        repeat_count=None, frequency='Monthly', day_of_month=31, month_of_year=None, frequency_days=None), **changes})


def test_month_end_recovers_configured_day_after_leap_february():
    assert list(occurrences(schedule(), date(2024, 1, 1), date(2024, 4, 30))) == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)]


def test_start_after_monthly_day_skips_to_next_month():
    entry = schedule(day_of_month=1)
    assert next_occurrence(entry, date(2024, 1, 1)) == date(2024, 2, 1)


def test_yearly_clamps_leap_day_and_restores_it():
    entry = schedule(start_date=date(2024, 2, 29), frequency='Yearly', month_of_year=2, day_of_month=29)
    assert list(occurrences(entry, date(2024, 1, 1), date(2028, 3, 1))) == [date(2024, 2, 29), date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28), date(2028, 2, 29)]


@pytest.mark.parametrize('mode,count,end,expected', [
    ('once', None, None, [date(2024, 1, 31)]),
    ('count', 2, None, [date(2024, 1, 31), date(2024, 2, 29)]),
    ('indefinite', None, date(2024, 2, 29), [date(2024, 1, 31), date(2024, 2, 29)]),
])
def test_repeat_modes_have_inclusive_bounds(mode, count, end, expected):
    assert list(occurrences(schedule(repeat_mode=mode, repeat_count=count, end_date=end), date(2024, 1, 1), date(2024, 6, 1))) == expected


def test_every_n_days_uses_real_month_occurrences_and_skips_old_cycles():
    entry = schedule(start_date=date(2024, 1, 31), frequency='EveryNDays', frequency_days=7)
    assert list(occurrences(entry, date(2024, 2, 1), date(2024, 2, 29))) == [date(2024, 2, 7), date(2024, 2, 14), date(2024, 2, 21), date(2024, 2, 28)]
    assert next_occurrence(entry, date(2026, 10, 19)) == date(2026, 10, 21)


@pytest.fixture
def db():
    engine = sa.create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([models.Client(id=1, name='automatic', general_settings={'currency': 'JPY', 'timezone': 'Asia/Tokyo'}), models.Client(id=2, name='other')])
        session.flush()
        session.add_all([models.Account(id=1, client_id=1, name='bank', account_type='asset'),
            models.Account(id=2, client_id=1, name='expense', account_type='expense'), models.Account(id=3, client_id=2, name='other bank', account_type='asset')])
        session.commit()
        yield session
    engine.dispose()


def payload(**changes):
    return schemas.RegistryEntryCreate(**{'name': 'subscription', 'kind': 'expense', 'amount': 100, 'currency': 'JPY',
        'source_account_id': 1, 'destination_account_id': 2, 'start_date': date(2026, 1, 1),
        'repeat_mode': 'indefinite', 'frequency': 'Monthly', 'day_of_month': 1, **changes}).model_dump()


def test_create_and_reactivate_do_not_backfill_and_currency_remains(db):
    entry = registry.create_entry(db, 1, payload(), today=date(2026, 10, 19))
    assert entry.next_due_date == date(2026, 11, 1)
    registry.update_entry(db, 1, entry.id, {'is_active': False}, today=date(2026, 10, 20))
    assert entry.next_due_date is None
    registry.update_entry(db, 1, entry.id, {'is_active': True}, today=date(2027, 1, 2))
    assert entry.next_due_date == date(2027, 2, 1)
    assert entry.currency == 'JPY'


def test_count_end_computed_on_save_and_finished_count_stays_finished(db):
    entry = registry.create_entry(db, 1, payload(start_date=date(2026, 1, 31), day_of_month=31, repeat_mode='count', repeat_count=3), today=date(2026, 1, 31))
    assert entry.end_date == date(2026, 3, 31)
    result = workflow.process_due(db, 1, today=date(2026, 4, 1))
    assert len(result['automatic_transactions'][0]['transaction_ids']) == 3
    assert entry.next_due_date is None
    registry.update_entry(db, 1, entry.id, {'note': 'done'}, today=date(2026, 4, 2))
    assert entry.next_due_date is None
    assert workflow.process_due(db, 1, today=date(2026, 4, 2))['automatic_transactions'] == []


def test_daily_catchup_caps_at_24_and_posts_balanced_journals_idempotently(db):
    entry = registry.create_entry(db, 1, payload(frequency='EveryNDays', frequency_days=1), today=date(2026, 1, 1))
    first = workflow.process_due(db, 1, today=date(2026, 2, 1))
    assert len(first['automatic_transactions'][0]['transaction_ids']) == 24
    assert entry.next_due_date == date(2026, 1, 25)
    second = workflow.process_due(db, 1, today=date(2026, 2, 1))
    assert len(second['automatic_transactions'][0]['transaction_ids']) == 8
    assert entry.next_due_date == date(2026, 2, 2)
    assert workflow.process_due(db, 1, today=date(2026, 2, 1))['automatic_transactions'] == []
    for tx in db.query(models.Transaction):
        assert tx.registry_entry_id == entry.id
        assert sum(leg.debit_minor for leg in tx.journal_entries) == sum(leg.credit_minor for leg in tx.journal_entries) == 100


def test_once_budget_scheduled_and_posting_share_one_date(db):
    entry = registry.create_entry(db, 1, payload(repeat_mode='once', start_date=date(2026, 10, 19)), today=date(2026, 10, 19))
    assert entry.frequency is None
    assert registry.registry_entry_amount_for_period(db, entry, '2026-10', date(2026, 10, 1), 1) == 100
    assert registry.registry_entry_amount_for_period(db, entry, '2026-11', date(2026, 11, 1), 1) == 0
    before = recording.scheduled_in_period(db, 1, '2026-10')['items']
    assert len(before) == 1 and before[0]['date'] == entry.start_date and not before[0]['posted']
    workflow.process_due(db, 1, today=date(2026, 10, 19))
    assert entry.next_due_date is None
    assert recording.scheduled_in_period(db, 1, '2026-10')['items'][0]['posted']
    assert recording.generated_in_period(db, 1, '2026-10')[0]['source'] == entry.name
    assert recording.generated_in_period(db, 2, '2026-10') == []


def test_budget_can_be_excluded_while_posting_remains_active(db):
    entry = registry.create_entry(db, 1, payload(frequency='EveryNDays', frequency_days=7, budget_active=False), today=date(2026, 1, 1))
    assert registry.registry_entry_amount_for_period(db, entry, '2026-01', date(2026, 1, 1), 1) == 0
    assert registry.registry_entry_amount_for_period(db, entry, '2026-01', date(2026, 1, 1), 1, budget_only=False) == 500
    assert len(recording.scheduled_in_period(db, 1, '2026-01')['items']) == 5
    assert workflow.process_due(db, 1, today=date(2026, 1, 1))['automatic_transactions']


def test_delete_keeps_transactions_and_nulls_provenance_without_sqlite_fk(db):
    entry = registry.create_entry(db, 1, payload(), today=date(2026, 1, 1))
    workflow.process_due(db, 1, today=date(2026, 1, 1))
    assert registry.delete_entry(db, 1, entry.id)
    db.commit(); db.expire_all()
    tx = db.query(models.Transaction).one()
    assert tx.registry_entry_id is None and len(tx.journal_entries) == 2


@pytest.mark.parametrize('field', ['source_account_id', 'destination_account_id', 'budget_account_id'])
def test_foreign_accounts_refused_before_writing(db, field):
    with pytest.raises(Invalid, match='belong'):
        registry.create_entry(db, 1, payload(**{field: 3}), today=date(2026, 1, 1))
    assert db.query(models.RegistryEntry).count() == 0


@pytest.mark.parametrize('changes', [{'frequency': None}, {'frequency': 'EveryNDays', 'frequency_days': None}, {'repeat_mode': 'count', 'repeat_count': None}, {'end_date': date(2025, 1, 1)}])
def test_invalid_schedules_refused(db, changes):
    with pytest.raises(Invalid):
        registry.create_entry(db, 1, payload(**changes), today=date(2026, 1, 1))
    assert db.query(models.RegistryEntry).count() == 0


def test_client_today_uses_timezone_at_utc_boundary(db, monkeypatch):
    # Patch the module object this file calls: another test may have imported a fresh copy into sys.modules.
    module = registry
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 18, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(module, 'datetime', Clock)
    assert registry.client_today(db, 1) == date(2026, 10, 19)


def test_generated_lists_depreciation_capsule_and_automatic_but_omits_manual(db):
    txs = [ledger_service.create_transaction(db, client_id=1, date=date(2026, 10, 19), amount_minor=100, currency='JPY', description=f'tx {i}', from_account_id=1, to_account_id=2) for i in range(3)]
    product = models.Product(client_id=1, name='equipment', auto_depreciation=True)
    db.add(product); db.flush()
    db.add(models.ProductDepreciation(client_id=1, product_id=product.id, transaction_id=txs[0].id, period='2026-10', amount_minor=100))
    db.add(models.TransactionProposal(client_id=1, origin='capsule', idempotency_key='rule:9', origin_ref={'rule_id': 9}, date=date(2026, 10, 19), description='reserve', amount_minor=100, currency='JPY', legs=[], status='posted', posted_transaction_id=txs[1].id))
    db.commit()
    found = recording.generated_in_period(db, 1, '2026-10')
    assert [(row['id'], row['source']) for row in found] == [(txs[0].id, '固定資産の減価'), (txs[1].id, '取り置きの規則')]


def legacy_data():
    def old(i, **changes):
        return {'id': i, 'name': f'old {i}', 'entry_type': 'service', 'is_active': True, 'generate_recurring': True,
                'auto_post': True, 'frequency': 'Monthly', 'day_of_month': 1, 'start_period': '2024-02', 'end_period': '2024-02', 'created_at': '2020-01-10T00:00:00', **changes}
    return {'products': [{'id': 5}], 'registry_entries': [old(1), old(2, generate_recurring=False), old(3, frequency='Irregular'), old(4, auto_post=False), old(5, source_product_id=5, auto_depreciation=True), old(6, entry_type='allocation', start_period=None, end_period=None)],
            'recurring_transactions': [{'id': 10, 'source_registry_entry_id': 1, 'next_due_date': '2024-02-20'}, {'id': 11, 'source_registry_entry_id': 5}],
            'transactions': [{'id': 20, 'recurring_transaction_id': 10}, {'id': 21, 'recurring_transaction_id': 11}, {'id': 22, 'recurring_transaction_id': None}]}


def test_legacy_conversion_preserves_dates_provenance_and_posting_choices():
    data = legacy_data()
    counts = migrate_automatic_data(data)
    assert counts == {'product_rows_deleted': 1, 'non_posting_disabled': 1, 'irregular_disabled': 1, 'manual_disabled': 1}
    assert data['products'][0]['auto_depreciation']
    assert [row['is_active'] for row in data['registry_entries']] == [True, False, False, False, True]
    assert data['registry_entries'][0]['start_date'] == '2024-02-01'
    assert data['registry_entries'][0]['end_date'] == '2024-02-29'
    assert data['registry_entries'][0]['next_due_date'] == '2024-02-20'
    assert data['registry_entries'][-1]['kind'] == 'transfer'
    assert data['registry_entries'][-1]['start_date'] == '2020-01-10'
    assert data['transactions'][0]['registry_entry_id'] == 1
    assert data['transactions'][1]['registry_entry_id'] is None
    assert all(not (REMOVED_FIELDS & row.keys()) for row in data['registry_entries'])
    assert 'recurring_transactions' not in data


def test_new_routes_reject_removed_fields_and_old_routes_are_absent(db):
    from fastapi.encoders import jsonable_encoder
    app = FastAPI()
    app.include_router(registry_entries.router); app.include_router(automatic_recordings.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)
    with TestClient(app) as http:
        response = http.post('/auto-transactions/', json=jsonable_encoder(payload(repeat_mode='once', start_date=date(2099, 1, 1))))
        assert response.status_code == 200, response.text
        assert response.json()['next_due_date'] == '2099-01-01'
        for field in REMOVED_FIELDS:
            assert http.post('/auto-transactions/', json={**jsonable_encoder(payload()), field: None}).status_code == 422
        assert http.get('/recurring/').status_code == 404
        assert http.get('/registry-entries/').status_code == 404
        assert http.post('/automatic-recordings/depreciation/1/post-due').status_code == 404


def test_alembic_upgrade_moves_rows_and_preserves_journal_headers():
    """Use a pre-wave fixture, including both cyclic links and the live FK names."""
    engine = sa.create_engine('sqlite://')
    meta = sa.MetaData()
    sa.Table('clients', meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('accounts', meta, sa.Column('id', sa.Integer, primary_key=True))
    products = sa.Table('products', meta, sa.Column('id', sa.Integer, primary_key=True))
    entries = sa.Table('registry_entries', meta,
        sa.Column('id', sa.Integer, primary_key=True), sa.Column('client_id', sa.Integer), sa.Column('name', sa.String),
        sa.Column('entry_type', sa.String), sa.Column('category', sa.String), sa.Column('amount_minor', sa.BigInteger),
        sa.Column('currency', sa.String), sa.Column('frequency', sa.String, nullable=False), sa.Column('frequency_days', sa.Integer),
        sa.Column('day_of_month', sa.Integer), sa.Column('month_of_year', sa.Integer), sa.Column('line_type', sa.String),
        sa.Column('budget_account_id', sa.Integer), sa.Column('source_account_id', sa.Integer), sa.Column('destination_account_id', sa.Integer),
        sa.Column('funding_capsule_id', sa.Integer), sa.Column('budget_treatment', sa.String), sa.Column('generate_recurring', sa.Boolean),
        sa.Column('auto_post', sa.Boolean), sa.Column('auto_depreciation', sa.Boolean), sa.Column('budget_active', sa.Boolean),
        sa.Column('is_active', sa.Boolean), sa.Column('source_product_id', sa.Integer, sa.ForeignKey('products.id')),
        sa.Column('source_recurring_transaction_id', sa.Integer, sa.ForeignKey('recurring_transactions.id', name='registry_entries_source_recurring_transaction_id_fkey')),
        sa.Column('note', sa.Text), sa.Column('start_period', sa.String), sa.Column('end_period', sa.String),
        sa.Column('created_at', sa.DateTime), sa.Column('updated_at', sa.DateTime))
    recurring = sa.Table('recurring_transactions', meta, sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('source_registry_entry_id', sa.Integer, sa.ForeignKey('registry_entries.id', name='recurring_transactions_source_registry_entry_id_fkey')),
        sa.Column('next_due_date', sa.Date))
    txs = sa.Table('transactions', meta, sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('recurring_transaction_id', sa.Integer, sa.ForeignKey('recurring_transactions.id', name='fk_transactions_recurring_transaction_id'), index=True),
        sa.Column('description', sa.String), sa.Column('amount_minor', sa.BigInteger))
    meta.create_all(engine)
    with engine.begin() as connection:
        data = legacy_data()
        connection.execute(products.insert(), [{'id': 5}])
        for row in data['registry_entries']:
            connection.execute(entries.insert(), {**row, 'client_id': 1, 'amount_minor': 123, 'currency': 'JPY', 'created_at': datetime(2020, 1, 10), 'auto_depreciation': row.get('auto_depreciation', False), 'source_product_id': row.get('source_product_id')})
        connection.execute(recurring.insert(), [{'id': 10, 'source_registry_entry_id': 1, 'next_due_date': date(2024, 2, 20)}, {'id': 11, 'source_registry_entry_id': 5, 'next_due_date': None}])
        connection.execute(txs.insert(), [{**row, 'description': 'preserved', 'amount_minor': 123} for row in data['transactions']])
        path = Path(__file__).parents[1] / 'alembic/versions/20261019_0076_auto_transactions.py'
        spec = importlib.util.spec_from_file_location('wp13_migration', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert 'recurring_transactions' not in sa.inspect(connection).get_table_names()
        rows = connection.execute(sa.text('SELECT id, kind, is_active, next_due_date FROM registry_entries ORDER BY id')).mappings().all()
        assert len(rows) == 5 and rows[0]['next_due_date'] == '2024-02-20'
        assert [bool(row['is_active']) for row in rows] == [True, False, False, False, True]
        assert connection.scalar(sa.text('SELECT auto_depreciation FROM products WHERE id=5')) == 1
        assert list(connection.execute(sa.text('SELECT registry_entry_id FROM transactions ORDER BY id')).scalars()) == [1, None, None]
        assert connection.scalar(sa.text('SELECT SUM(amount_minor) FROM transactions')) == 369
        assert REMOVED_FIELDS.isdisjoint({column['name'] for column in sa.inspect(connection).get_columns('registry_entries')})
    engine.dispose()


def test_zero_goal_saving_advances_without_a_zero_ledger_entry(db):
    entry = registry.create_entry(db, 1, payload(amount=0), today=date(2026, 1, 1))
    workflow.process_due(db, 1, today=date(2026, 1, 1))
    assert entry.next_due_date == date(2026, 2, 1)
    assert db.query(models.Transaction).count() == 0


def test_reactivation_on_posted_day_does_not_duplicate_an_occurrence(db):
    entry = registry.create_entry(db, 1, payload(), today=date(2026, 1, 1))
    workflow.process_due(db, 1, today=date(2026, 1, 1))
    registry.update_entry(db, 1, entry.id, {'is_active': False}, today=date(2026, 1, 1))
    registry.update_entry(db, 1, entry.id, {'is_active': True}, today=date(2026, 1, 1))
    workflow.process_due(db, 1, today=date(2026, 1, 1))
    assert db.query(models.Transaction).count() == 1
    assert entry.next_due_date == date(2026, 2, 1)


def test_monthly_action_add_and_stop_use_the_same_schedule_and_keep_history(db):
    from app.workflows.monthly_action_workflow import create_action, apply_action
    from fastapi.encoders import jsonable_encoder
    action = create_action(db, 1, '2026-01', 'add_auto_transaction', jsonable_encoder(payload()), '2026-02')
    applied = apply_action(db, 1, action['id'])
    entry_id = applied['result']['registry_entry_id']
    entry = db.get(models.RegistryEntry, entry_id)
    assert entry.kind == 'expense'
    assert entry.next_due_date >= registry.client_today(db, 1)
    stop = create_action(db, 1, '2026-01', 'stop_auto_transaction', {'registry_entry_id': entry_id}, '2026-02')
    assert apply_action(db, 1, stop['id'])['result']['is_active'] is False
    assert not entry.is_active and entry.next_due_date is None


def test_legacy_saved_actions_and_approved_ai_requests_use_new_ids_and_require_approval():
    data = legacy_data()
    data['accounts'] = [{'id': 1, 'account_type': 'asset'}, {'id': 2, 'account_type': 'expense'}]
    data['monthly_actions'] = [{'kind': 'pause_recurring', 'payload': {'recurring_id': 10}, 'target_id': 10},
        {'kind': 'add_recurring', 'source_period': '2026-01', 'target_period': '2026-02', 'payload': {'name': 'new', 'amount': 100, 'from_account_id': 1, 'to_account_id': 2, 'frequency': 'Monthly'}}]
    data['ai_change_requests'] = [{'resource': 'recurring_transactions', 'status': 'approved', 'target_ref': {'id': 10}, 'input_payload': {'amount': 200}, 'approved_by_client_id': 1}]
    migrate_automatic_data(data)
    assert data['monthly_actions'][0]['kind'] == 'stop_auto_transaction'
    assert data['monthly_actions'][0]['payload'] == {'registry_entry_id': 1}
    assert data['monthly_actions'][0]['target_id'] == 1
    added = data['monthly_actions'][1]
    assert added['kind'] == 'add_auto_transaction' and added['payload']['start_date'] == '2026-02-01'
    assert added['payload']['kind'] == 'expense'
    request = data['ai_change_requests'][0]
    assert request['resource'] == 'auto_transactions' and request['target_ref'] == {'id': 1}
    assert request['status'] == 'pending' and request['approved_by_client_id'] is None
    assert request['input_payload']['amount'] == 200


def test_legacy_backup_moves_product_switch_and_transaction_fk_without_posting(db):
    from app.services.data_transfer_service import export_client, import_client
    from app.domain.transfer import _sha256
    entry = registry.create_entry(db, 1, payload(), today=date(2026, 1, 1))
    workflow.process_due(db, 1, today=date(2026, 1, 1))
    product = models.Product(client_id=1, name='asset', category='equipment', last_unit_price_minor=100, is_asset=True)
    db.add(product); db.commit()
    document = export_client(db, db.get(models.Client, 1))
    data = document['data']
    data['registry_entries'][0] = {'id': entry.id, 'name': 'old subscription', 'entry_type': 'service', 'amount': 100, 'currency': 'JPY',
        'frequency': 'Monthly', 'day_of_month': 1, 'source_account_id': 1, 'destination_account_id': 2,
        'generate_recurring': False, 'auto_post': True, 'is_active': True, 'created_at': '2026-01-01T00:00:00'}
    data['registry_entries'].append({'id': 999, 'name': 'asset copy', 'entry_type': 'asset', 'source_product_id': product.id, 'auto_depreciation': True})
    data['recurring_transactions'] = [{'id': 77, 'source_registry_entry_id': entry.id, 'next_due_date': '2026-02-01'}]
    for tx in data['transactions']:
        tx.pop('registry_entry_id', None); tx['recurring_transaction_id'] = 77
    checksums = {key: _sha256(value) for key, value in data.items()}
    manifest = {'counts': {key: len(value) for key, value in data.items()}, 'checksums': checksums, 'payload_checksum': _sha256({'data': data, 'checksums': checksums})}
    result = import_client(db, db.get(models.Client, 2), data=data, version=23, manifest=manifest)
    assert result['status'] == 'ok'
    restored = db.query(models.RegistryEntry).filter_by(client_id=2).one()
    assert not restored.is_active and restored.next_due_date == date(2026, 2, 1)
    assert db.query(models.Product).filter_by(client_id=2).one().auto_depreciation
    tx = db.query(models.Transaction).filter_by(client_id=2).one()
    assert tx.registry_entry_id == restored.id
    assert len(tx.journal_entries) == 2
    assert db.query(models.Transaction).filter_by(client_id=1).count() == 1


def test_pre_registry_backup_preserves_standalone_recurring_and_its_postings():
    data = {'accounts': [{'id': 1, 'account_type': 'income'}, {'id': 2, 'account_type': 'asset'}],
        'recurring_transactions': [{'id': 50, 'name': 'salary', 'amount': 100, 'currency': 'JPY', 'from_account_id': 1, 'to_account_id': 2, 'frequency': 'Monthly', 'day_of_month': 25, 'next_due_date': '2026-10-25', 'created_at': '2026-01-01'}],
        'transactions': [{'id': 9, 'recurring_transaction_id': 50}]}
    counts = migrate_automatic_data(data)
    entry = data['registry_entries'][0]
    assert counts['orphan_recurring_restored'] == 1
    assert entry['kind'] == 'income' and entry['is_active']
    assert entry['source_account_id'] == 1 and entry['next_due_date'] == '2026-10-25'
    assert data['transactions'][0]['registry_entry_id'] == entry['id']


def test_legacy_ai_update_keeps_requested_account_and_start_month_changes():
    data = legacy_data()
    data['registry_entries'][0].update(source_account_id=1, destination_account_id=2)
    data['accounts'] = [{'id': 1, 'account_type': 'asset'}, {'id': 2, 'account_type': 'expense'}, {'id': 3, 'account_type': 'income'}, {'id': 4, 'account_type': 'asset'}]
    data['ai_change_requests'] = [{'resource': 'recurring_transactions', 'status': 'pending', 'target_ref': {'id': 10},
                                 'input_payload': {'from_account_id': 3, 'to_account_id': 4, 'start_period': '2026-12'}}]
    migrate_automatic_data(data)
    body = data['ai_change_requests'][0]['input_payload']
    assert (body['source_account_id'], body['destination_account_id'], body['kind']) == (3, 4, 'income')
    assert body['start_date'] == '2026-12-01'


def test_inactive_product_definition_never_starts_automatic_depreciation():
    data = legacy_data()
    data['registry_entries'][4]['is_active'] = False
    counts = migrate_automatic_data(data)
    assert not data['products'][0]['auto_depreciation']
    assert counts['inactive_depreciation_disabled'] == 1


def test_ai_preview_computes_the_same_count_end_and_clears_once_fields(db):
    from app.workflows.ai_change_request_workflow import _preview_automatic_create
    from fastapi.encoders import jsonable_encoder
    preview = _preview_automatic_create(db, 1, jsonable_encoder(payload(repeat_mode='count', repeat_count=3, start_date=date(2096, 1, 31), day_of_month=31)))
    assert preview['after_snapshot']['end_date'] == '2096-03-31'
    assert preview['after_snapshot']['next_due_date'] == '2096-01-31'
    once = _preview_automatic_create(db, 1, jsonable_encoder(payload(repeat_mode='once', start_date=date(2096, 1, 31))))
    assert once['input_payload']['frequency'] is None
    assert once['input_payload']['repeat_count'] is None


@pytest.mark.parametrize('status', ['applied', 'rejected', 'failed'])
def test_closed_ai_history_keeps_its_original_snapshots(status):
    from copy import deepcopy
    data = legacy_data()
    request = {'resource': 'recurring_transactions', 'status': status, 'target_ref': {'id': 10},
               'input_payload': {'amount': 99}, 'before_snapshot': {'amount': 12}, 'after_snapshot': {'amount': 99},
               'diff': {'changes': [{'field': 'amount', 'before': 12, 'after': 99}]}}
    data['ai_change_requests'] = [deepcopy(request)]
    migrate_automatic_data(data)
    assert data['ai_change_requests'] == [request]
