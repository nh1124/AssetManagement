from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.services.money_storage import minor_fields, rule_data
from app import models
from app.database import Base
from app.domain.transfer import DATA_COLLECTIONS, EXPORT_VERSION, validate_import_payload
from app.services.data_transfer_service import export_client

# Freeze the file format independently of both ORM metadata and the exporter.
FORMAT_FIELDS = {
    "accounts": ["id","name","account_type","balance","parent_id","expected_return","role","role_target_amount","liability_closing_day","liability_payment_day","liability_payment_month_offset","liability_payment_policy","liability_minimum_payment","liability_fixed_payment_amount","liability_installment_months","liability_revolving_rate","is_active"],
    "products": ["id","name","category","location","last_unit_price","units_per_purchase","frequency_days","last_purchase_date","is_asset","lifespan_months","budget_account_id","funding_capsule_id","budget_treatment","purchase_price","purchase_date"],
    "simulation_configs": ["id","user_id","annual_return","tax_rate","is_nisa","monthly_savings","volatility","inflation_rate"],
    "recurring_transactions": ["id","name","amount","currency","from_account_id","to_account_id","frequency","day_of_month","month_of_year","next_due_date","start_period","end_period","auto_post","is_active","source_registry_entry_id","created_at"],
    "registry_entries": ["id","name","entry_type","category","amount","currency","frequency","frequency_days","day_of_month","month_of_year","line_type","budget_account_id","source_account_id","destination_account_id","funding_capsule_id","budget_treatment","generate_recurring","budget_active","is_active","source_product_id","source_recurring_transaction_id","note","start_period","end_period","created_at","updated_at"],
    "quick_templates": ["id","tray","name","template_kind","description","category","default_currency","default_from_account_id","default_to_account_id","config","sort_order","is_active","created_at","updated_at"],
    "transaction_batches": ["id","quick_template_id","label","source","input_payload","created_at"],
    "life_events": ["id","name","start_date","target_date","target_amount","priority","note","active_plan_basis","active_plan_label","plan_status_override","created_at"],
    "transactions": ["id","date","description","amount","currency","batch_id","recurring_transaction_id","created_at"],
    "journal_entries": ["id","transaction_id","account_id","debit","credit","memo","sort_order"],
    "budget_plans": ["id","name","description","is_default","sort_order","created_at","updated_at"],
    "monthly_plan_lines": ["id","target_period","line_type","target_type","target_id","account_id","source_account_id","name","amount","source","source_kind","identity_key","manual_override","cash_treatment","plan_id","is_active","created_at","updated_at"],
    "period_reviews": ["id","start_date","end_date","label","reflection","next_actions","created_at","updated_at"],
    "monthly_actions": ["id","source_period","target_period","proposal_id","kind","description","amount","target_id","payload","result","status","idempotency_key","created_at","applied_at"],
    "milestones": ["id","life_event_id","date","target_amount","note","source","source_snapshot","is_active_plan","created_at"],
    "capsules": ["id","name","target_amount","monthly_contribution","current_balance","account_id","life_event_id","capsule_type","target_amount_source","monthly_contribution_source","created_at"],
    "capsule_rules": ["id","capsule_id","trigger_type","trigger_category","trigger_description","source_mode","source_account_id","amount_type","amount_value","is_active","created_at"],
    "capsule_holdings": ["id","capsule_id","account_id","held_amount","note","updated_at"],
    "simulation_scenarios": ["id","life_event_id","name","description","annual_return","inflation","monthly_savings","contribution_schedule","allocation_mode","created_at","updated_at"],
    "exchange_rates": ["id","base_currency","quote_currency","rate","as_of_date","source","created_at","updated_at"],
}

STAMP = datetime(2026, 10, 1, 12)
PERIOD = "2026-10"


def _seed_client(db, client_id, base, marker):
    rows = {}

    def add(model, offset, **values):
        values["id"] = base + offset
        if hasattr(model, "client_id"):
            values["client_id"] = client_id
        for field in ("created_at", "updated_at"):
            if hasattr(model, field):
                values[field] = STAMP
        money_names = {
            "monthly_plan_lines": ("amount",), "life_events": ("target_amount",),
            "milestones": ("target_amount",), "capsules": ("target_amount", "monthly_contribution", "current_balance"),
            "capsule_holdings": ("held_amount",), "monthly_actions": ("amount",),
            "products": ("last_unit_price", "purchase_price"), "simulation_configs": ("monthly_savings",),
            "simulation_scenarios": ("monthly_savings",), "registry_entries": ("amount",),
            "recurring_transactions": ("amount",),
        }
        if model.__tablename__ == "capsule_rules":
            values = rule_data(values, "JPY")
        elif model.__tablename__ in money_names:
            values = minor_fields(values, values.get("currency") or "JPY", *money_names[model.__tablename__])
        row = model(**values)
        db.add(row)
        rows.setdefault(model.__tablename__, []).append(row)
        return row

    client = models.Client(
        id=client_id, name=marker, username=marker, email=f"{marker}@example.com",
        general_settings={"currency": "JPY", "owner": marker}, ai_config={},
        created_at=STAMP, updated_at=STAMP,
    )
    db.add(client)
    cash = add(models.Account, 1, name=f"{marker}-cash", account_type="asset", balance=-100)
    expense = add(models.Account, 2, name=f"{marker}-expense", account_type="expense", balance=100)
    goal = add(models.LifeEvent, 3, name=marker, target_date=date(2027, 1, 1), target_amount=1000)
    capsule = add(
        models.Capsule, 4, name=marker, account_id=cash.id, life_event_id=goal.id,
        target_amount=1000, monthly_contribution=10, current_balance=0,
    )
    product = add(
        models.Product, 5, name=marker, category="expense", last_unit_price=100,
        budget_account_id=expense.id, funding_capsule_id=capsule.id,
    )
    add(models.SimulationConfig, 6, user_id=client_id)
    registry = add(
        models.RegistryEntry, 7, name=marker, amount=100, budget_account_id=expense.id,
        source_account_id=cash.id, destination_account_id=expense.id,
        funding_capsule_id=capsule.id, source_product_id=product.id, generate_recurring=True,
    )
    db.flush()
    recurring = add(
        models.RecurringTransaction, 8, name=marker, amount=100, frequency="Monthly",
        from_account_id=cash.id, to_account_id=expense.id, source_registry_entry_id=registry.id,
        next_due_date=date(2026, 10, 31),
    )
    db.flush()
    registry.source_recurring_transaction_id = recurring.id
    template = add(
        models.QuickTemplate, 9, name=marker, tray="expense", template_kind="simple",
        default_from_account_id=cash.id, default_to_account_id=expense.id,
        config={"owner": marker, "nested": [{"account_id": cash.id, "capsule_id": capsule.id}]},
    )
    batch = add(
        models.TransactionBatch, 10, quick_template_id=template.id, label=marker,
        input_payload={"nested": {"account_id": cash.id, "life_event_id": goal.id}},
    )
    tx = add(
        models.Transaction, 11, date=date(2026, 10, 2), description=marker, amount_minor=100,
        batch_id=batch.id, recurring_transaction_id=recurring.id,
    )
    db.flush()
    add(models.JournalEntry, 12, transaction_id=tx.id, account_id=expense.id, debit_minor=100, credit_minor=0, memo=marker, sort_order=0)
    add(models.JournalEntry, 13, transaction_id=tx.id, account_id=cash.id, debit_minor=0, credit_minor=100, memo=marker, sort_order=1)
    plan = add(models.BudgetPlan, 14, name=marker, is_default=True, sort_order=20)
    add(
        models.MonthlyPlanLine, 15, plan_id=plan.id, target_period=PERIOD, line_type="expense",
        target_type="account", target_id=expense.id, account_id=expense.id,
        source_account_id=cash.id, name=marker, amount=100,
        identity_key=f"{marker}-expense",
    )
    add(
        models.PeriodReview, 16, start_date=date(2026, 10, 1), end_date=date(2026, 11, 1),
        label=marker, reflection=marker, next_actions=marker,
    )
    add(
        models.MonthlyAction, 17, source_period=PERIOD, target_period="2026-11",
        proposal_id=marker, kind="goal_allocation", description=marker, target_id=goal.id,
        idempotency_key=marker,
        payload={"nested": [{"account_id": cash.id, "capsule_id": capsule.id}]},
        result={"nested": {"transaction_id": tx.id, "batch_id": batch.id}},
    )
    add(
        models.Milestone, 18, life_event_id=goal.id, date=date(2027, 1, 1),
        target_amount=1000, note=marker, source_snapshot={"nested": {"account_id": cash.id}},
    )
    add(
        models.CapsuleRule, 19, capsule_id=capsule.id, trigger_type="expense",
        source_account_id=cash.id, amount_value=10,
    )
    add(models.CapsuleHolding, 20, capsule_id=capsule.id, account_id=cash.id, held_amount=0, note=marker)
    add(
        models.SimulationScenario, 21, life_event_id=goal.id, name=marker,
        annual_return=5, inflation=2, monthly_savings=10,
        contribution_schedule=[{"period": PERIOD, "amount": 10, "account_id": cash.id}],
    )
    add(models.ExchangeRate, 22, base_currency="USD", quote_currency="JPY", rate=150, as_of_date=date(2026, 10, 1))
    db.commit()
    return client, rows


@pytest.fixture
def seeded():
    engine = create_engine("sqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        client, rows = _seed_client(db, 101, 10000, "source-client")
        yield db, client, rows
    engine.dispose()


def _format_roundtrip(document):
    return json.loads(json.dumps(document))


def test_every_collection_has_exact_format_columns_and_roundtrips(seeded):
    db, client, rows = seeded
    document = _format_roundtrip(export_client(db, client))
    assert list(document["data"]) == DATA_COLLECTIONS == list(FORMAT_FIELDS)
    for collection, fields in FORMAT_FIELDS.items():
        exported = document["data"][collection]
        assert exported
        assert {row["id"] for row in exported} == {row.id for row in rows[collection]}
        for row in exported:
            assert list(row) == fields, collection
    validation = validate_import_payload(document["data"], document["version"], document["manifest"])
    assert validation["error_count"] == 0, validation


def _checksum(value):
    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item

    encoded = json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def test_manifest_counts_and_checksums_describe_exported_data(seeded):
    db, client, _ = seeded
    document = _format_roundtrip(export_client(db, client))
    data, manifest = document["data"], document["manifest"]
    checksums = {key: _checksum(value) for key, value in data.items()}
    assert manifest["counts"] == {key: len(value) for key, value in data.items()}
    assert manifest["checksums"] == checksums
    assert manifest["payload_checksum"] == _checksum({"data": data, "checksums": checksums})
    assert manifest["client_id"] == client.id
    assert manifest["exported_at"] == document["exported_at"]


def test_version_uses_domain_format_version(seeded):
    db, client, _ = seeded
    document = export_client(db, client)
    assert document["version"] == document["manifest"]["export_version"] == EXPORT_VERSION


def test_second_client_is_absent_even_from_nested_references_and_health(seeded):
    db, client, rows = seeded
    other, other_rows = _seed_client(db, 202, 20000, "foreign-client")
    document = _format_roundtrip(export_client(db, client))
    foreign_ids = {row.id for collection in other_rows.values() for row in collection} | {other.id}

    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert "foreign-client" not in key
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
        elif isinstance(value, str):
            assert "foreign-client" not in value
            assert value not in {str(item) for item in foreign_ids}
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            assert value not in foreign_ids

    check(document)
    for collection, exported in document["data"].items():
        assert {row["id"] for row in exported} == {row.id for row in rows[collection]}
    template = document["data"]["quick_templates"][0]
    assert template["config"]["nested"][0]["account_id"] == rows["accounts"][0].id
    assert document["data"]["monthly_actions"][0]["result"]["nested"]["transaction_id"] == rows["transactions"][0].id


def test_ordered_accounts_and_budget_plans_keep_their_declared_order(seeded):
    # All exported tables are ordered; budget_plans orders by sort_order then id.
    db, client, rows = seeded
    db.add_all([
        models.Account(id=9999, client_id=client.id, name="later insertion", account_type="asset"),
        models.BudgetPlan(id=10030, client_id=client.id, name="first tie", sort_order=5, created_at=STAMP),
        models.BudgetPlan(id=10029, client_id=client.id, name="second insertion", sort_order=5, created_at=STAMP),
    ])
    db.commit()
    document = export_client(db, client)
    assert [row["id"] for row in document["data"]["accounts"]] == [9999, 10001, 10002]
    assert [row["id"] for row in document["data"]["budget_plans"]] == [10029, 10030, rows["budget_plans"][0].id]
    assert document["data"] == export_client(db, client)["data"]

