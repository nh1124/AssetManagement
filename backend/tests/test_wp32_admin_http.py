"""Admin plane HTTP contracts; no TestClient blocking portal."""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta

import httpx
import pyotp
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.admin.auth import COOKIE
from app.admin.main import create_app
from app.config import AppConfig, settings
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.admin_permissions import ALL_PERMISSIONS, STEP_UP_REQUIRED
from app.main import app as user_app
from app.security import decrypt_key
from app.services import admin_auth_service as admins
from app.utils.jwt import create_typed_token
from app.utils.password import hash_password

# Every route (including documentation) must be classified here. Missing entries
# fail the inventory test. Permission rows also drive live refusal/step-up tests.
ROUTES = {
    ('GET', '/openapi.json'): 'public', ('GET', '/docs'): 'public',
    ('GET', '/docs/oauth2-redirect'): 'public', ('GET', '/redoc'): 'public', ('GET', '/health'): 'public',
    ('POST', '/admin/api/session'): 'public', ('DELETE', '/admin/api/session'): 'session',
    ('POST', '/admin/api/session/password'): 'session', ('POST', '/admin/api/session/code'): 'session',
    ('POST', '/admin/api/session/mfa-setup/start'): 'session', ('POST', '/admin/api/session/mfa-setup/verify'): 'session',
    ('POST', '/admin/api/session/step-up'): 'session',
    ('GET', '/admin/api/me'): 'session', ('GET', '/admin/api/me/sessions'): 'session',
    ('DELETE', '/admin/api/me/sessions/{id}'): 'session', ('POST', '/admin/api/me/password'): 'session',
    ('GET', '/admin/api/admins'): 'admins.manage', ('POST', '/admin/api/admins'): 'admins.manage',
    ('PATCH', '/admin/api/admins/{id}'): 'admins.manage', ('POST', '/admin/api/admins/{id}/mfa-reset'): 'admins.manage',
    ('GET', '/admin/api/overview'): 'accounts.read', ('GET', '/admin/api/clients'): 'accounts.read',
    ('GET', '/admin/api/clients/{id}'): 'accounts.read', ('POST', '/admin/api/clients'): 'accounts.manage',
    ('POST', '/admin/api/clients/{id}/suspend'): 'accounts.manage',
    ('POST', '/admin/api/clients/{id}/reactivate'): 'accounts.manage',
    ('POST', '/admin/api/clients/{id}/approve'): 'accounts.manage',
    ('POST', '/admin/api/clients/{id}/unlock'): 'accounts.manage',
    ('POST', '/admin/api/clients/{id}/sign-out'): 'accounts.manage',
    ('POST', '/admin/api/clients/{id}/password-reset'): 'accounts.credentials',
    ('POST', '/admin/api/clients/{id}/mfa-reset'): 'accounts.credentials',
    ('GET', '/admin/api/clients/{id}/health'): 'health.read',
    ('POST', '/admin/api/clients/{id}/health/repair'): 'health.repair',
    ('GET', '/admin/api/settings'): 'session', ('PUT', '/admin/api/settings/{key}'): 'settings.manage',
    ('GET', '/admin/api/audit'): 'audit.read',
}
PASSWORD = 'initial-password-123'
NEW_PASSWORD = 'different-password-456'


@pytest.fixture
def http():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        owner, _ = admins.create(db, 'owner', PASSWORD, 'cli:test', permissions=ALL_PERMISSIONS)
        owner.mfa_enabled = True
        db.add(models.Client(id=1, username='client', name='Client', password_hash=hash_password('password123')))
        db.commit()
    app = create_app()

    def db_override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = db_override

    def request(method, path, raw=None, *, target=None, **kwargs):
        headers = {'Origin': 'http://localhost:18300', 'X-Request-ID': 'wp32-http-correlation', **kwargs.pop('headers', {})}
        headers = {key: value for key, value in headers.items() if value is not None}
        if raw:
            headers['Cookie'] = f'{COOKIE}={raw}'
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=target or app, raise_app_exceptions=False), base_url='http://localhost') as client:
                pending = asyncio.create_task(client.request(method, path, headers=headers, **kwargs))
                deadline = asyncio.get_running_loop().time() + 30
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.01)
                    if asyncio.get_running_loop().time() > deadline:
                        pending.cancel()
                        raise AssertionError(f'{method} {path} timed out')
                return pending.result()
        with sessions() as db:
            before = db.query(models.AdminAuditLog).filter_by(result='ok').count()
        response = asyncio.run(run())
        if method in {'POST', 'PUT', 'PATCH', 'DELETE'} and path.startswith('/admin/api') and response.status_code == 200:
            with sessions() as db:
                rows = db.query(models.AdminAuditLog).filter_by(result='ok').order_by(models.AdminAuditLog.id).all()
                assert len(rows) == before + 1, (method, path, 'exactly one successful audit')
                assert rows[-1].admin_user_id is not None
                assert rows[-1].actor == f'admin:{rows[-1].admin_user_id}'
                assert rows[-1].ip == '127.0.0.1'
                assert rows[-1].correlation_id == 'wp32-http-correlation'
                detail = json.dumps(rows[-1].detail)
                assert not any(marker in detail for marker in ('password', 'secret', 'cookie', 'token', 'otpauth'))
                if isinstance(response.json(), dict) and 'temporary_password' in response.json():
                    assert response.json()['temporary_password'] not in detail
            assert response.headers['Cache-Control'] == 'no-store'
        return response
    yield request, sessions, app
    engine.dispose()


def cookie(response):
    assert response.status_code == 200, response.text
    return response.cookies[COOKIE]


def full_session(sessions, *, permissions=None, stepped=True, username='owner'):
    with sessions() as db:
        admin = admins.get_by_username(db, username)
        if permissions is not None:
            # Keep a second active manager to exercise permission removals safely.
            if not admins.get_by_username(db, 'backup'):
                backup, _ = admins.create(db, 'backup', PASSWORD, 'test', permissions=ALL_PERMISSIONS)
            admins.set_permissions(db, admin, permissions, 'test')
        return admins.create_session(db, admin, stepped_up=stepped)


def totp(sessions, username='owner'):
    with sessions() as db:
        admin = admins.get_by_username(db, username)
        return pyotp.TOTP(decrypt_key(admin.totp_secret_encrypted)).now()


def body_for(path):
    if path.endswith('/me/password'):
        return {'current_password': PASSWORD, 'new_password': NEW_PASSWORD}
    if path.endswith('/suspend'):
        return {'reason': 'test reason'}
    if path == '/admin/api/admins':
        return {'username': 'created', 'preset': 'viewer'}
    if path == '/admin/api/clients':
        return {'username': 'created', 'name': 'Created'}
    if '/settings/' in path:
        return {'value': 'approval'}
    if path.endswith('/admins/{id}'):
        return {'is_active': True, 'permissions': list(ALL_PERMISSIONS)}
    return {}


def concrete(path):
    return path.replace('{id}', '1').replace('{key}', 'registration_mode')


def test_inventory_and_separation(http):
    request, sessions, app = http
    actual = {(method, r.path) for r in app.routes for method in r.methods if method != 'HEAD'}
    assert actual == set(ROUTES)
    assert not any(path.startswith('/admin') for path in user_app.openapi()['paths'])
    assert all(p.startswith('/admin/api') or p in {'/health'} for p in app.openapi()['paths'])
    token = create_typed_token(user_id='1', username='client', token_type='access')
    for (method, path), permission in ROUTES.items():
        if not path.startswith('/admin/api') or (method, path) == ('POST', '/admin/api/session'):
            continue
        response = request(method, concrete(path), headers={'Authorization': 'Bearer ' + token}, json=body_for(path))
        assert response.status_code == 401, (path, response.text)
    boundary = FastAPI(exception_handlers=user_app.exception_handlers)
    @boundary.get('/me')
    def me(client=Depends(get_current_client)):
        return {'id': client.id}
    boundary.dependency_overrides[get_db] = app.dependency_overrides[get_db]
    assert request('GET', '/me', full_session(sessions), target=boundary).status_code == 401


def test_guards_headers_and_localization(http):
    request, _, app = http
    for method, headers, expected in [('GET', {'Host': 'evil.invalid'}, 400),
                                      ('POST', {'Origin': None}, 403), ('POST', {'Origin': ''}, 403), ('POST', {'Origin': 'https://evil.invalid'}, 403)]:
        response = request(method, '/admin/api/session', headers=headers, json={})
        assert response.status_code == expected
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert request('GET', '/health', headers={'Origin': 'https://evil.invalid'}).status_code == 200
    assert request('GET', '/admin/api/me', headers={'Accept-Language': 'ja'}).json()['detail'] == '管理者としてサインインしてください。'
    @app.get('/explode')
    def explode():
        raise RuntimeError('test')
    assert request('GET', '/explode').headers['X-Frame-Options'] == 'DENY'


def test_cli_login_code_rotation_replay_and_cookie(http):
    request, sessions, _ = http
    first = request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD})
    raw = cookie(first)
    assert first.json() == {'stage': 'mfa', 'admin': {'username': 'owner'}}
    flags = first.headers['set-cookie'].lower()
    assert 'httponly' in flags and 'samesite=strict' in flags and 'path=/' in flags
    assert 'max-age' not in flags and 'expires=' not in flags and 'secure' not in flags
    assert request('GET', '/admin/api/me', raw).status_code == 401
    assert request('POST', '/admin/api/session/password', raw, json={'new_password': NEW_PASSWORD}).status_code == 401
    code = totp(sessions)
    response = request('POST', '/admin/api/session/code', raw, json={'code': code})
    full = cookie(response)
    assert full != raw and response.json()['stage'] is None
    assert request('POST', '/admin/api/session/code', raw, json={'code': code}).status_code == 401
    assert request('GET', '/admin/api/me', full).status_code == 200
    assert request('POST', '/admin/api/session/step-up', full, json={'code': code}).status_code == 401
    with sessions() as db:
        row = db.get(models.AdminSession, hashlib.sha256(full.encode()).hexdigest())
        assert row.stepped_up_at and row.stage is None
        assert timedelta(hours=7, minutes=59) < row.expires_at - row.created_at <= timedelta(hours=8)
        assert db.get(models.AdminSession, hashlib.sha256(raw.encode()).hexdigest()).revoked_at


def test_web_admin_and_reset_state_machine(http):
    request, sessions, _ = http
    owner = full_session(sessions)
    created = request('POST', '/admin/api/admins', owner, json={'username': 'new', 'preset': 'viewer'})
    assert created.status_code == 200, created.text
    for temporary in [created.json()['temporary_password'], None]:
        if temporary is None:
            reset = request('POST', f"/admin/api/admins/{created.json()['id']}/mfa-reset", owner)
            temporary = reset.json()['temporary_password']
        response = request('POST', '/admin/api/session', json={'username': 'new', 'password': temporary})
        raw = cookie(response)
        assert response.json()['stage'] == 'password_change'
        assert request('POST', '/admin/api/session/password', raw, json={'new_password': temporary}).status_code == 400
        assert request('POST', '/admin/api/session/password', raw, json={'new_password': 'short'}).status_code == 400
        response = request('POST', '/admin/api/session/password', raw, json={'new_password': NEW_PASSWORD})
        changed = cookie(response)
        assert changed != raw and response.json()['stage'] == 'mfa_setup'
        assert request('POST', '/admin/api/session/password', raw, json={'new_password': NEW_PASSWORD}).status_code == 401
        setup = request('POST', '/admin/api/session/mfa-setup/start', changed)
        setup_cookie = cookie(setup)
        assert setup_cookie != changed
        assert request('POST', '/admin/api/session/mfa-setup/start', changed).status_code == 401
        key = setup.json()['manual_entry_key']
        verified = request('POST', '/admin/api/session/mfa-setup/verify', setup_cookie, json={'code': pyotp.TOTP(key).now()})
        full = cookie(verified)
        assert full != setup_cookie and verified.json()['stage'] is None
        assert request('POST', '/admin/api/session/mfa-setup/verify', setup_cookie, json={'code': pyotp.TOTP(key).now()}).status_code == 401
        assert request('GET', '/admin/api/me', full).status_code == 200
    with sessions() as db:
        rows = db.query(models.AdminAuditLog).filter_by(result='ok').all()
        assert all(row.admin_user_id and row.ip == '127.0.0.1' and row.correlation_id == 'wp32-http-correlation' for row in rows)
        assert all('password' not in json.dumps(row.detail) and key not in json.dumps(row.detail) for row in rows)


@pytest.mark.parametrize('change', ['idle', 'absolute', 'revoked', 'inactive', 'restricted_expiry'])
def test_session_rejection(http, change):
    request, sessions, _ = http
    raw = full_session(sessions)
    with sessions() as db:
        row = db.get(models.AdminSession, hashlib.sha256(raw.encode()).hexdigest())
        if change == 'idle':
            row.last_seen_at = datetime.utcnow() - timedelta(minutes=31)
        elif change in {'absolute', 'restricted_expiry'}:
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
            if change == 'restricted_expiry':
                row.stage = 'mfa'
        elif change == 'revoked':
            row.revoked_at = datetime.utcnow()
        else:
            admins.get_by_id(db, row.admin_user_id).is_active = False
        db.commit()
    assert request('GET', '/admin/api/me', raw).status_code == 401
    assert request('POST', '/admin/api/session/code', raw, json={'code': '000000'}).status_code == 401


def test_lockout_correct_password_does_not_reset(http):
    request, sessions, _ = http
    for _ in range(2):
        assert request('POST', '/admin/api/session', json={'username': 'owner', 'password': 'wrong'}).status_code == 401
    raw = cookie(request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD}))
    with sessions() as db:
        assert admins.get_by_username(db, 'owner').failed_login_count == 2
    for _ in range(3):
        assert request('POST', '/admin/api/session/code', raw, json={'code': 'invalid'}).status_code == 401
    assert request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD}).status_code == 429
    assert request('POST', '/admin/api/session', json={'username': 'unknown', 'password': PASSWORD}).status_code == 401
    with sessions() as db:
        admin = admins.get_by_username(db, 'owner')
        assert admin.failed_login_count == 5
        admin.locked_until = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    full = cookie(request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD, 'code': totp(sessions)}))
    with sessions() as db:
        assert admins.get_by_username(db, 'owner').failed_login_count == 0
    logout = request('DELETE', '/admin/api/session', full)
    assert logout.status_code == 200 and 'Max-Age=0' in logout.headers['set-cookie']
    assert request('GET', '/admin/api/me', full).status_code == 401


PERMISSION_ROUTES = [(method, path, permission) for (method, path), permission in ROUTES.items() if permission not in {'session', 'public'}]


@pytest.mark.parametrize('method,path,permission', PERMISSION_ROUTES)
def test_permissions_and_step_up(http, method, path, permission):
    request, sessions, _ = http
    raw = full_session(sessions, permissions=())
    response = request(method, concrete(path), raw, json=body_for(path))
    assert response.status_code == 403, response.text
    with sessions() as db:
        row = db.query(models.AdminAuditLog).filter_by(action='permission.denied').one()
        assert row.detail == {'path': concrete(path), 'permission': permission}
        assert row.result == 'refused' and row.admin_user_id == 1
    raw = full_session(sessions, permissions=ALL_PERMISSIONS, stepped=False)
    if permission in STEP_UP_REQUIRED:
        response = request(method, concrete(path), raw, json=body_for(path))
        assert response.status_code == 403 and response.json()['code'] == 'step_up_required'
        response = request('POST', '/admin/api/session/step-up', raw, json={'code': totp(sessions)})
        assert response.status_code == 200, response.text
    with sessions() as db:
        before = db.query(models.AdminAuditLog).filter_by(result='ok').count()
    response = request(method, concrete(path), raw, json=body_for(path))
    assert response.status_code == 200, response.text
    if method != 'GET':
        with sessions() as db:
            rows = db.query(models.AdminAuditLog).filter_by(result='ok').order_by(models.AdminAuditLog.id).all()
            assert len(rows) == before + 1
            assert rows[-1].admin_user_id == 1 and rows[-1].actor == 'admin:1'
            assert rows[-1].ip == '127.0.0.1' and rows[-1].correlation_id == 'wp32-http-correlation'
            assert not any(word in json.dumps(rows[-1].detail) for word in ['password', 'secret', 'cookie', 'token'])
        assert response.headers['Cache-Control'] == 'no-store'
        if 'temporary_password' in response.json():
            assert response.json()['temporary_password'] not in json.dumps(rows[-1].detail)


def test_last_manager_and_own_sessions(http):
    request, sessions, _ = http
    raw = full_session(sessions)
    for update in ({'is_active': False}, {'permissions': []}):
        response = request('PATCH', '/admin/api/admins/1', raw, json=update)
        assert response.status_code == 403, response.text
    other = full_session(sessions)
    own = request('GET', '/admin/api/me/sessions', raw).json()
    assert len(own) == 2
    with sessions() as db:
        admin, _ = admins.create(db, 'other', PASSWORD, 'test')
        admin.mfa_enabled = True
        db.commit()
        foreign = admins.create_session(db, admin)
    foreign_id = hashlib.sha256(foreign.encode()).hexdigest()
    assert request('DELETE', '/admin/api/me/sessions/' + foreign_id, raw).status_code == 404
    response = request('POST', '/admin/api/me/password', raw, json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert request('GET', '/admin/api/me', raw).status_code == 200
    assert request('GET', '/admin/api/me', other).status_code == 401
    assert request('GET', '/admin/api/me', foreign).status_code == 200
    response = request('DELETE', '/admin/api/me/sessions/' + hashlib.sha256(raw.encode()).hexdigest(), raw)
    assert response.status_code == 200
    assert request('GET', '/admin/api/me', raw).status_code == 401


def test_overview_scoping_settings_and_ui(http, tmp_path):
    request, sessions, app = http
    raw = full_session(sessions, permissions={'accounts.read'})
    data = request('GET', '/admin/api/overview', raw).json()
    assert 'health' not in data and 'recent_audit' not in data
    assert data['clients']['total'] == 1 and data['clients']['without_totp'] == 1
    assert request('GET', '/admin/api/settings', raw).json()['registration_mode']['default'] == 'open'
    (tmp_path / 'index.html').write_text('admin SPA')
    (tmp_path / 'asset.js').write_text('asset')
    spa = create_app(AppConfig(admin_ui_dir=str(tmp_path)))
    assert request('GET', '/deep/link', target=spa).text == 'admin SPA'
    assert request('GET', '/asset.js', target=spa).text == 'asset'
    assert request('GET', '/admin/api/missing', target=spa).status_code == 404
    assert request('GET', '/admin/api', target=spa).status_code == 404


def test_production_wildcards_and_secure_cookie(http, monkeypatch):
    for key in ['admin_allowed_hosts', 'admin_allowed_origins']:
        config = AppConfig(app_env='production', **{key: '*'})
        with pytest.raises(RuntimeError, match=key.upper()):
            config.validate_production_settings()
    request, _, _ = http
    monkeypatch.setattr(settings, 'admin_cookie_secure', True)
    response = request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD})
    assert 'Secure' in response.headers['set-cookie']


def test_forced_password_change_with_existing_factor(http):
    request, sessions, _ = http
    with sessions() as db:
        admin = admins.get_by_username(db, 'owner')
        admin.must_change_password = True
        db.commit()
    response = request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD, 'code': totp(sessions)})
    raw = cookie(response)
    assert response.json()['stage'] == 'password_change'
    changed = request('POST', '/admin/api/session/password', raw, json={'new_password': NEW_PASSWORD})
    raw2 = cookie(changed)
    assert changed.json()['stage'] == 'mfa'
    assert request('POST', '/admin/api/session/mfa-setup/start', raw2).status_code == 401
    full = request('POST', '/admin/api/session/code', raw2, json={'code': totp(sessions)})
    assert full.status_code == 200 and full.json()['stage'] is None


def test_unconfirmed_cli_factor_and_restricted_routes(http):
    request, sessions, _ = http
    with sessions() as db:
        admin = admins.get_by_username(db, 'owner')
        admin.mfa_enabled = False
        db.commit()
    response = request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD})
    raw = cookie(response)
    assert response.json()['stage'] == 'mfa_setup'
    for (method, path), classification in ROUTES.items():
        if classification == 'public' or path.startswith('/admin/api/session/mfa-setup'):
            continue
        response = request(method, concrete(path), raw, json=body_for(path))
        assert response.status_code == 401, (path, response.text)
    with sessions() as db:
        row = db.get(models.AdminSession, hashlib.sha256(raw.encode()).hexdigest())
        assert row.expires_at - row.created_at == timedelta(minutes=10)
    response = request('DELETE', '/admin/api/session', raw)
    assert response.status_code == 401


def test_configured_timeouts_touch_and_stale_step_up(http, monkeypatch):
    request, sessions, _ = http
    monkeypatch.setattr(settings, 'admin_session_max_hours', 2)
    monkeypatch.setattr(settings, 'admin_session_idle_minutes', 7)
    raw = full_session(sessions)
    with sessions() as db:
        row = db.get(models.AdminSession, hashlib.sha256(raw.encode()).hexdigest())
        assert row.expires_at - row.created_at == timedelta(hours=2)
        row.last_seen_at = datetime.utcnow() - timedelta(minutes=6)
        row.stepped_up_at = datetime.utcnow() - timedelta(minutes=6)
        before = row.last_seen_at
        db.commit()
    response = request('GET', '/admin/api/admins', raw)
    assert response.status_code == 403 and response.json()['code'] == 'step_up_required'
    assert request('GET', '/admin/api/me', raw).status_code == 200
    with sessions() as db:
        row = db.get(models.AdminSession, hashlib.sha256(raw.encode()).hexdigest())
        assert row.last_seen_at > before
        row.last_seen_at = datetime.utcnow() - timedelta(minutes=8)
        db.commit()
    assert request('GET', '/admin/api/me', raw).status_code == 401


def test_settings_lockout_and_inline_wrong_code(http):
    from app.services import system_settings_service
    request, sessions, _ = http
    with sessions() as db:
        system_settings_service.set(db, 'login_lockout_threshold', 3, 'test')
        system_settings_service.set(db, 'login_lockout_minutes', 4, 'test')
    for _ in range(3):
        response = request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD, 'code': 'invalid'})
        assert response.status_code == 401
    with sessions() as db:
        admin = admins.get_by_username(db, 'owner')
        assert admin.failed_login_count == 3
        assert timedelta(minutes=3, seconds=55) < admin.locked_until - datetime.utcnow() <= timedelta(minutes=4)
    assert request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD}).status_code == 429


def test_own_password_step_up_and_each_session_mutation_audit(http):
    request, sessions, _ = http
    raw = full_session(sessions, stepped=False)
    response = request('POST', '/admin/api/me/password', raw, json={'current_password': PASSWORD, 'new_password': NEW_PASSWORD})
    assert response.status_code == 403 and response.json()['code'] == 'step_up_required'
    operations = [
        ('POST', '/admin/api/session/step-up', {'code': totp(sessions)}, 'session.step_up'),
        ('POST', '/admin/api/me/password', {'current_password': PASSWORD, 'new_password': NEW_PASSWORD}, 'admin.password'),
        ('DELETE', '/admin/api/session', {}, 'session.logout'),
    ]
    for method, path, body, action in operations:
        with sessions() as db:
            before = db.query(models.AdminAuditLog).filter_by(result='ok').count()
        response = request(method, path, raw, json=body)
        assert response.status_code == 200, response.text
        with sessions() as db:
            rows = db.query(models.AdminAuditLog).filter_by(result='ok').order_by(models.AdminAuditLog.id).all()
            assert len(rows) == before + 1 and rows[-1].action == action
            assert rows[-1].admin_user_id == 1 and rows[-1].detail == {}


def test_overview_health_cap_and_permission_filtering(http, monkeypatch):
    from app.services import data_health_service
    request, sessions, _ = http
    with sessions() as db:
        db.add_all([models.Client(username=f'client{i}', name=f'Client {i}', is_active=True) for i in range(2, 203)])
        db.add(models.Client(username='suspended', name='Suspended', is_active=False))
        db.commit()
    inspected = []
    def check(db, client_id):
        inspected.append(client_id)
        return {'issues': [{'audience': 'admin', 'count': 2}, {'audience': 'user', 'count': 3}, {'audience': 'user', 'count': 0}]}
    monkeypatch.setattr(data_health_service, 'check_data_health', check)
    raw = full_session(sessions)
    response = request('GET', '/admin/api/overview', raw)
    data = response.json()
    assert response.status_code == 200
    assert len(inspected) == 200 and data['health']['truncated'] is True
    assert data['health']['limit'] == 200 and data['health']['checked_clients'] == 200
    assert data['health']['clients'][0] == {'client_id': 1, 'admin': 1, 'user': 1}
    assert 'recent_audit' in data


def test_http_logs_component_and_no_credentials(http, caplog):
    request, sessions, _ = http
    caplog.set_level('INFO', logger='app.request')
    response = request('POST', '/admin/api/session', json={'username': 'owner', 'password': PASSWORD, 'code': totp(sessions)})
    raw = cookie(response)
    request('GET', '/admin/api/me', raw)
    records = [r for r in caplog.records if r.name == 'app.request']
    assert records and all(r.fields['component'] == 'admin' for r in records)
    serialized = json.dumps([r.fields for r in records])
    assert PASSWORD not in serialized and raw not in serialized


def test_no_startup_and_health_never_opens_database(http):
    request, _, app = http
    def unavailable_database():
        raise AssertionError('liveness must not open a database session')
    app.dependency_overrides[get_db] = unavailable_database
    assert app.router.on_startup == [] and app.router.on_shutdown == []
    assert request('GET', '/health').json() == {'status': 'healthy'}


def test_production_has_no_documentation(http):
    from cryptography.fernet import Fernet
    request, _, _ = http
    config = AppConfig(app_env='production', jwt_secret_key='x' * 32,
                       mcp_jwt_secret='y' * 32, encryption_key=Fernet.generate_key().decode())
    app = create_app(config)
    for path in ['/docs', '/redoc', '/openapi.json']:
        assert request('GET', path, target=app).status_code == 404


def test_app_specific_session_configuration(http):
    request, sessions, original = http
    app = create_app(AppConfig(admin_cookie_secure=True, admin_session_max_hours=1, admin_session_idle_minutes=2))
    app.dependency_overrides[get_db] = original.dependency_overrides[get_db]
    response = request('POST', '/admin/api/session', target=app,
                       json={'username': 'owner', 'password': PASSWORD, 'code': totp(sessions)})
    raw = cookie(response)
    assert 'Secure' in response.headers['set-cookie']
    with sessions() as db:
        row = db.get(models.AdminSession, hashlib.sha256(raw.encode()).hexdigest())
        assert row.expires_at - row.created_at == timedelta(hours=1)
        row.last_seen_at = datetime.utcnow() - timedelta(minutes=3)
        db.commit()
    assert request('GET', '/admin/api/me', raw, target=app).status_code == 401


def test_oversized_new_password_is_localized_refusal(http):
    request, sessions, _ = http
    raw = full_session(sessions)
    response = request('POST', '/admin/api/me/password', raw,
                       json={'current_password': PASSWORD, 'new_password': 'あ' * 25},
                       headers={'Accept-Language': 'ja'})
    assert response.status_code == 400
    assert response.json()['detail'] == '管理者パスワードはUTF-8で72バイト以内にしてください。'
    assert request('GET', '/admin/api/me', raw).status_code == 200
