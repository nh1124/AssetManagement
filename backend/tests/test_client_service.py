from unittest.mock import patch

from scenario_fixtures import goal_scenario_id

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.routers import auth
from backend.app.services import budget_plan_store, client_service, goal_service, ledger_service
from backend.app.utils.password import hash_password, verify_password


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _client(db, *, username="tester", **fields):
    values = {
        "name": username,
        "username": username,
        "email": f"{username}@example.com",
        "password_hash": "original-hash",
        "ai_config": {"existing": True},
        "general_settings": {"currency": "JPY"},
    }
    values.update(fields)
    client = models.Client(**values)
    db.add(client)
    db.commit()
    return client


@pytest.mark.parametrize(
    "accessor, field, lower, upper",
    [
        (client_service.get_by_username, "username", "alice", "ALICE"),
        (client_service.get_by_email, "email", "alice@example.com", "ALICE@example.com"),
    ],
)
def test_identity_lookups_are_exact_without_case_folding(db, accessor, field, lower, upper):
    first = _client(db, **{"username": "first", field: lower})
    second = _client(db, **{"username": "second", field: upper})
    assert accessor(db, lower) is first
    assert accessor(db, upper) is second
    assert accessor(db, lower[:3]) is None
    assert accessor(db, lower.capitalize()) is None
    assert accessor(db, f" {lower}") is None
    assert accessor(db, "missing") is None


def test_register_stores_one_client_with_the_supplied_hash(db):
    password = "password123"
    password_hash = hash_password(password)
    client = client_service.register(
        db, name="Alice", username="alice", email="alice@example.com",
        password_hash=password_hash,
    )
    db.expire_all()
    stored = db.query(models.Client).one()
    assert stored.id == client.id
    assert (stored.name, stored.username, stored.email) == ("Alice", "alice", "alice@example.com")
    assert stored.password_hash == password_hash
    assert stored.password_hash != password
    assert verify_password(password, stored.password_hash)
    assert (stored.ai_config, stored.general_settings, stored.is_active) == ({}, {}, True)


def test_register_rolls_back_a_duplicate_display_name(db):
    existing = _client(db, name="Shared")
    with pytest.raises(IntegrityError):
        client_service.register(
            db, name="Shared", username="second", email=None, password_hash="hash",
        )
    assert db.query(models.Client).one() is existing
    assert client_service.get_by_username(db, "second") is None


def test_unique_display_name_preserves_free_name_and_skips_two_taken_names(db):
    assert client_service.unique_display_name(db, "Shared") == "Shared"
    _client(db, name="Shared")
    second_name = client_service.unique_display_name(db, "Shared")
    assert second_name == "Shared-2"
    _client(db, username="second", name=second_name)
    third_name = client_service.unique_display_name(db, "Shared")
    assert third_name == "Shared-3"
    assert len({"Shared", second_name, third_name}) == 3


def test_get_active_by_id_excludes_inactive_and_missing_clients(db):
    active = _client(db)
    inactive = _client(db, username="inactive", is_active=False)
    assert client_service.get_active_by_id(db, active.id) is active
    assert client_service.get_active_by_id(db, inactive.id) is None
    assert client_service.get_active_by_id(db, 999999) is None


def test_username_active_filter_is_optional_without_changing_exact_match(db):
    inactive = _client(db, is_active=False)
    assert client_service.get_by_username(db, "tester") is inactive
    assert client_service.get_by_email(db, "tester@example.com") is inactive
    assert client_service.get_by_username(db, "tester", active_only=True) is None
    active = _client(db, username="active")
    assert client_service.get_by_username(db, "active", active_only=True) is active
    assert client_service.get_by_username(db, "ACTIVE", active_only=True) is None


@pytest.mark.parametrize("fields", [
    {}, {"name": "Renamed"}, {"email": "new@example.com"},
    {"password_hash": "new-hash"}, {"name": "Renamed", "email": "new@example.com"},
])
def test_update_profile_changes_only_supplied_fields(db, fields):
    client = _client(db)
    original = {
        "name": client.name, "email": client.email, "password_hash": client.password_hash,
        "username": client.username, "is_active": client.is_active,
        "ai_config": dict(client.ai_config), "general_settings": dict(client.general_settings),
    }
    assert client_service.update_profile(db, client, fields) is client
    db.expire_all()
    assert {key: getattr(client, key) for key in original} == {**original, **fields}


def test_update_profile_commit_false_leaves_the_change_rollbackable(db):
    client = _client(db)
    client_service.update_profile(db, client, {"name": "Renamed"}, commit=False)
    assert client.name == "Renamed"
    db.rollback()
    assert client.name == "tester"


def test_registration_keeps_password_hashing_in_the_router(db):
    password = "password123"
    with patch.object(auth, "hash_password", wraps=hash_password) as hashing:
        result = auth.register(auth.RegisterRequest(
            name="Alice", username=" ALICE ", email="ALICE@example.com", password=password,
        ), db)
    hashing.assert_called_once_with(password)
    stored = db.query(models.Client).one()
    assert result == {"message": "User registered successfully", "client_id": stored.id}
    assert (stored.name, stored.username, stored.email) == ("Alice", "alice", "alice@example.com")
    assert verify_password(password, stored.password_hash)


def test_profile_router_keeps_truthy_field_selection_and_password_hashing(db):
    client = _client(db)
    original = (client.name, client.email, client.password_hash)
    assert auth.update_profile(auth.ProfileUpdate(name="", email="", password=""), db, client) == {
        "message": "Profile updated successfully",
    }
    assert (client.name, client.email, client.password_hash) == original
    with patch.object(auth, "hash_password", wraps=hash_password) as hashing:
        auth.update_profile(auth.ProfileUpdate(password="changed123"), db, client)
    hashing.assert_called_once_with("changed123")
    assert (client.name, client.email) == original[:2]
    assert verify_password("changed123", client.password_hash)


def test_list_asset_accounts_filters_type_and_client_but_keeps_inactive_assets(db):
    client = _client(db)
    other = _client(db, username="other")
    active = models.Account(client_id=client.id, name="Active", account_type="asset")
    inactive = models.Account(client_id=client.id, name="Inactive", account_type="asset", is_active=False)
    expense = models.Account(client_id=client.id, name="Expense", account_type="expense")
    foreign = models.Account(client_id=other.id, name="Foreign", account_type="asset")
    db.add_all([active, inactive, expense, foreign])
    db.commit()
    assert ledger_service.list_asset_accounts(db, client.id) == [active, inactive]
    assert ledger_service.list_asset_accounts(db, other.id) == [foreign]
    assert ledger_service.list_asset_accounts(db, 999999) == []


def test_get_plan_is_client_scoped_and_never_creates_a_default(db):
    client = _client(db)
    other = _client(db, username="other")
    own = models.BudgetPlan(client_id=client.id, name="Own", is_default=False)
    foreign = models.BudgetPlan(client_id=other.id, name="Foreign", is_default=True)
    db.add_all([own, foreign])
    db.commit()
    assert budget_plan_store.get_plan(db, client.id, own.id) is own
    assert budget_plan_store.get_plan(db, client.id, foreign.id) is None
    assert budget_plan_store.get_plan(db, client.id, 999999) is None
    assert budget_plan_store.get_plan(db, 999999, own.id) is None
    assert db.query(models.BudgetPlan).count() == 2
    assert own.is_default is False


def test_existing_goal_list_excludes_another_clients_rows(db):
    client = _client(db)
    other = _client(db, username="other")
    own = models.LifeEvent(scenario_id=goal_scenario_id(db, client.id), client_id=client.id, name="Own")
    foreign = models.LifeEvent(scenario_id=goal_scenario_id(db, other.id), client_id=other.id, name="Foreign")
    db.add_all([own, foreign])
    db.commit()
    assert goal_service.list_goals(db, client.id) == [own]
    assert goal_service.list_goals(db, 999999) == []
