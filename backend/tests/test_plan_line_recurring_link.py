"""Plan-line recurring context comes from the registry, never stored input."""

from app.services.money_storage import to_minor

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.services.budget_plan_service import get_budget_summary
from app.services.registry_service import upsert_registry_from_recurring_payload


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    session.add(models.Client(
        id=1,
        name="test",
        general_settings={},
        ai_config={},
    ))
    session.add_all([
        models.Account(
            client_id=1,
            name="bank",
            account_type="asset",
        ),
        models.Account(
            client_id=1,
            name="subscriptions",
            account_type="expense",
        ),
    ])
    session.flush()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_registry_generated_plan_line_reports_recurring_definition(db):
    accounts = {row.name: row.id for row in db.query(models.Account).all()}
    recurring = upsert_registry_from_recurring_payload(
        db=db,
        client_id=1,
        payload=dict(
            name="subscription",
            amount=1200,
            frequency="Monthly",
            from_account_id=accounts["bank"],
            to_account_id=accounts["subscriptions"],
        ),
    )
    entry = db.get(models.RegistryEntry, recurring.source_registry_entry_id)
    assert entry.generate_recurring is True
    # Exercise the stored-line merge as well as the registry's virtual projection.
    db.add(models.MonthlyPlanLine(
        client_id=1,
        target_period="2026-10",
        line_type="expense",
        target_type="account",
        target_id=accounts["subscriptions"],
        account_id=accounts["subscriptions"],
        source_account_id=accounts["bank"],
        source_kind="registry",
        amount_minor=to_minor(1200, "JPY"),
        name="subscription",
        is_active=True,
    ))
    db.commit()
    lines = get_budget_summary(db, 1, "2026-10")["plan_lines"]
    line = next(line for line in lines if entry.id in line.get("registry_entry_ids", []))
    assert line["id"] is not None
    assert line["recurring_transaction_id"] == recurring.id
    assert schemas.MonthlyPlanLine.model_validate(line).recurring_transaction_id == recurring.id


def test_plan_line_without_registry_reports_no_recurring_definition(db):
    db.add(models.MonthlyPlanLine(
        client_id=1,
        target_period="2026-10",
        line_type="expense",
        target_type="manual",
        name="manual expense",
        amount_minor=to_minor(500, "JPY"),
        is_active=True,
    ))
    db.commit()
    lines = get_budget_summary(db, 1, "2026-10")["plan_lines"]
    line = next(line for line in lines if line["name"] == "manual expense")
    assert line["recurring_transaction_id"] is None
    assert schemas.MonthlyPlanLine.model_validate(line).recurring_transaction_id is None


def test_plan_line_create_rejects_recurring_transaction_id():
    with pytest.raises(ValidationError) as exc:
        schemas.MonthlyPlanLineCreate(
            target_period="2026-10",
            line_type="expense",
            recurring_transaction_id=11,
        )
    assert any(
        error["loc"] == ("recurring_transaction_id",) and error["type"] == "extra_forbidden"
        for error in exc.value.errors()
    )
