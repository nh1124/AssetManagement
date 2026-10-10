from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models, schemas
    from backend.app.database import Base
    from backend.app.routers.registry_entries import create_registry_entry, enrich_entry, update_registry_entry
    from backend.app.services.registry_service import upsert_registry_from_recurring_payload
    from backend.app.services.data_health_service import check_data_health
    from backend.app.services.budget_context import BudgetContext
    from backend.app.services.budget_registry_lines import registry_plan_lines
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models, schemas  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers.registry_entries import create_registry_entry, enrich_entry, update_registry_entry  # type: ignore[no-redef]
    from app.services.registry_service import upsert_registry_from_recurring_payload  # type: ignore[no-redef]
    from app.services.data_health_service import check_data_health  # type: ignore[no-redef]
    from app.services.budget_context import BudgetContext  # type: ignore[no-redef]
    from app.services.budget_registry_lines import registry_plan_lines  # type: ignore[no-redef]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
    session.add_all([
        models.Account(client_id=1, name="bank", account_type="asset", balance=100000),
        models.Account(client_id=1, name="subscriptions", account_type="expense", balance=0),
    ])
    session.flush()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _payload(db):
    accounts = {row.name: row.id for row in db.query(models.Account).all()}
    return dict(name="subscription", amount=1200, frequency="Monthly",
                from_account_id=accounts["bank"], to_account_id=accounts["subscriptions"])


def _issues(db):
    db.flush()
    return {issue["code"]: issue for issue in check_data_health(db, 1)["issues"]}


def test_registry_created_definition_has_no_health_violations(db):
    upsert_registry_from_recurring_payload(db, 1, _payload(db))
    issues = _issues(db)
    for code in ("recurring_without_registry", "recurring_budget_inactive"):
        assert issues[code]["count"] == 0
        assert issues[code]["items"] == []


@pytest.mark.parametrize("foreign_client", [False, True], ids=["missing", "another_client"])
def test_recurring_with_dangling_registry_is_reported(db, foreign_client):
    # SQLite leaves FKs off; missing pins check logic despite PostgreSQL rejecting it.
    if foreign_client:
        db.add(models.Client(id=2, name="other", general_settings={}, ai_config={}))
        db.add(models.RegistryEntry(id=999, client_id=2, name="other entry"))
    recurring = models.RecurringTransaction(client_id=1, **_payload(db), source_registry_entry_id=999)
    db.add(recurring)
    issue = _issues(db)["recurring_without_registry"]
    assert issue["count"] == 1
    assert issue["items"][0]["recurring_id"] == recurring.id
    assert issue["items"][0]["source_registry_entry_id"] == 999
    assert issue["items"][0]["next_due_date"] is None
    assert issue["items"][0]["problem"] == "dangling_registry_entry"


def test_recurring_budget_inactive_clears_when_budget_enabled(db):
    entry = models.RegistryEntry(client_id=1, name="subscription", line_type="expense",
                                 generate_recurring=True, budget_active=False)
    db.add(entry)
    issue = _issues(db)["recurring_budget_inactive"]
    assert issue["count"] == 1
    assert issue["severity"] == "error"
    assert issue["repairable"] is False
    assert issue["items"] == [{
        "registry_entry_id": entry.id, "name": "subscription", "line_type": "expense",
        "generate_recurring": True, "budget_active": False, "problem": "auto_posts_but_not_budgeted",
    }]
    entry.budget_active = True
    assert _issues(db)["recurring_budget_inactive"]["count"] == 0


def test_inactive_rows_and_other_clients_are_excluded(db):
    db.add(models.Client(id=2, name="other", general_settings={}, ai_config={}))
    inactive_entry = models.RegistryEntry(
        client_id=1,
        name="inactive",
        is_active=False,
        generate_recurring=True,
        budget_active=False,
    )
    other_entry = models.RegistryEntry(
        client_id=2,
        name="other",
        generate_recurring=True,
        budget_active=False,
    )
    db.add_all([inactive_entry, other_entry])
    db.flush()
    db.add_all([
        models.RecurringTransaction(
            client_id=1,
            name="inactive",
            is_active=False,
            source_registry_entry_id=inactive_entry.id,
        ),
        models.RecurringTransaction(
            client_id=2,
            name="other",
            source_registry_entry_id=other_entry.id,
        ),
    ])
    issues = _issues(db)
    assert issues["recurring_without_registry"]["count"] == 0
    assert issues["recurring_budget_inactive"]["count"] == 0


def _registry_payload(db, generate_recurring):
    data = _payload(db)
    return schemas.RegistryEntryCreate(name=data["name"], amount=data["amount"],
        source_account_id=data["from_account_id"], destination_account_id=data["to_account_id"],
        budget_account_id=data["to_account_id"], generate_recurring=generate_recurring, budget_active=False)


def test_registry_router_create_forces_budget_active(db):
    result = create_registry_entry(_registry_payload(db, True), db, db.get(models.Client, 1))
    assert result["budget_active"] is True
    assert db.get(models.RegistryEntry, result["id"]).budget_active is True
    assert _issues(db)["recurring_budget_inactive"]["count"] == 0


def test_registry_router_update_forces_budget_active(db):
    result = create_registry_entry(_registry_payload(db, False), db, db.get(models.Client, 1))
    assert result["budget_active"] is False
    updated = update_registry_entry(result["id"], _registry_payload(db, True), db, db.get(models.Client, 1))
    assert updated["budget_active"] is True
    assert db.get(models.RegistryEntry, result["id"]).budget_active is True
    assert _issues(db)["recurring_budget_inactive"]["count"] == 0


def test_registry_plan_lines_do_not_project_a_definition_of_an_inactive_entry(db):
    entry = models.RegistryEntry(
        client_id=1,
        name="inactive owner",
        is_active=False,
    )
    db.add(entry)
    db.flush()
    db.add(models.RecurringTransaction(
        client_id=1,
        **_payload(db),
        source_registry_entry_id=entry.id,
    ))
    db.commit()
    lines = registry_plan_lines(BudgetContext(db, 1), "2026-10")
    assert not any(line["name"] == "subscription" for line in lines)
    assert lines == []


def test_enrich_entry_uses_live_registry_fields(db):
    recurring = upsert_registry_from_recurring_payload(db, 1, _payload(db))
    db.commit()
    entry = db.get(models.RegistryEntry, recurring.source_registry_entry_id)
    result = enrich_entry(entry)
    assert "transaction_type" not in result
    assert result["generate_recurring"] == entry.generate_recurring
    assert result["budget_active"] == entry.budget_active
    assert result["source_recurring_transaction_id"] == entry.source_recurring_transaction_id
