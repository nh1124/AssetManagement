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
    "accounts": ["id","name","account_type","liability_closing_day","liability_payment_day","liability_payment_month_offset","liability_payment_policy","liability_minimum_payment","liability_fixed_payment_amount","liability_installment_months","liability_revolving_rate","is_active"],
    "products": ["id","name","category","location","last_unit_price","units_per_purchase","frequency_days","last_purchase_date","is_asset","lifespan_months","budget_account_id","funding_capsule_id","budget_treatment","purchase_price","purchase_date","auto_depreciation","depreciation_method","depreciation_annual_rate","depreciation_interval","depreciation_start_date","depreciation_expense_account_id","depreciation_asset_account_id"],
    "product_depreciations": ["id","product_id","period","transaction_id","amount_minor","created_at"],
    "simulation_configs": ["id","user_id","annual_return","tax_rate","is_nisa","volatility","inflation_rate","horizon_years"],
    "registry_entries": ["id","name","kind","amount","currency","source_account_id","destination_account_id","budget_account_id","repeat_mode","frequency","frequency_days","day_of_month","month_of_year","start_date","end_date","repeat_count","next_due_date","budget_active","is_active","note","created_at","updated_at"],
    "transaction_batches": ["id","label","source","input_payload","created_at"],
    "life_events": ["id","scenario_id","lineage","name","target_date","target_amount","priority","note","condition_mode","direction","account_id","interest_rate","borrowing_event_id","repeat_count","created_at"],
    "life_event_links": ["id","from_event_id","to_event_id","kind","offset_months","note","created_at"],
    "life_scenarios": ["id","name","annual_return","inflation","horizon_years","is_goal","created_at","updated_at"],
    "scenario_contribution_plans": ["id","scenario_id","account_id","start_period","monthly_amount_minor","annual_return","note","created_at"],
    "household_members": ["id","name","relation","birth_date","created_at"],
    "life_event_conditions": ["id","life_event_id","metric","comparator","threshold_minor","threshold_number","threshold_date","reference_id","note","created_at"],
    "transactions": ["id","date","description","amount","currency","batch_id","registry_entry_id","created_at"],
    "journal_entries": ["id","transaction_id","account_id","capsule_id","debit","credit","memo","sort_order"],
    "budget_plans": ["id","name","description","is_default","sort_order","created_at","updated_at"],
    "monthly_plan_lines": ["id","target_period","line_type","target_type","target_id","account_id","source_account_id","name","amount","source","source_kind","identity_key","manual_override","cash_treatment","plan_id","is_active","created_at","updated_at"],
    "period_reviews": ["id","start_date","end_date","label","reflection","next_actions","created_at","updated_at"],
    "period_closes": ["id","period","closed_at","note"],
    "monthly_actions": ["id","source_period","target_period","proposal_id","kind","description","amount","target_id","payload","result","status","idempotency_key","created_at","applied_at"],
    "capsules": ["id","name","target_amount","monthly_contribution","capsule_type","target_amount_source","monthly_contribution_source","goal_event_id","created_at"],
    "capsule_drawdowns": ["id","capsule_id","transaction_id","kind","amount_minor","note","created_at"],
    "capsule_funding_sources": ["id","capsule_id","account_id","target_amount","max_share_bp","sort_order","created_at","updated_at"],
    "capsule_rules": ["id","capsule_id","trigger_type","trigger_category","trigger_description","trigger_account_id","source_mode","source_account_id","destination_account_id","amount_type","amount_value","is_active","created_at"],
    "fx_tracked_currencies": ["currency","created_at"],
    "exchange_rates": ["id","base_currency","quote_currency","rate","as_of_date","source","created_at","updated_at"],
    "goal_budget_reflections": ["id","scenario_id","applied_at","start_period","end_period","summary"],
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
            "capsules": ("target_amount", "monthly_contribution"),
            "monthly_actions": ("amount",),
            "capsule_funding_sources": ("target_amount",),
            "products": ("last_unit_price", "purchase_price"), "registry_entries": ("amount",),
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
        general_settings={"currency": "JPY", "owner": marker},
        created_at=STAMP, updated_at=STAMP,
    )
    db.add(client)
    cash = add(models.Account, 1, name=f"{marker}-cash", account_type="asset")
    expense = add(models.Account, 2, name=f"{marker}-expense", account_type="expense")
    scenario = add(models.LifeScenario, 36, name="保存案", annual_return=7.0, inflation=1.0, horizon_years=12, is_goal=True)
    db.flush()
    goal = add(models.LifeEvent, 3, scenario_id=scenario.id, name=marker, target_date=date(2027, 1, 1), target_amount=1000)
    next_goal = add(models.LifeEvent, 31, scenario_id=scenario.id, name=f"{marker}-next", target_date=date(2028, 1, 1), target_amount=500)
    add(models.LifeEventLink, 32, from_event_id=goal.id, to_event_id=next_goal.id,
        kind="after", offset_months=12, note=marker)
    capsule = add(
        models.Capsule, 4, name=marker,
        target_amount=1000, monthly_contribution=10,
    )
    member = add(models.HouseholdMember, 34, name="子", relation="長女", birth_date=date(2010, 4, 1))
    add(models.LifeEventCondition, 35, life_event_id=goal.id, metric="member_age", comparator="gte",
        threshold_number=18, reference_id=member.id, note="入学")
    product = add(
        models.Product, 5, name=marker, category="expense", last_unit_price=100,
        budget_account_id=expense.id, funding_capsule_id=capsule.id,
        is_asset=True, lifespan_months=24, purchase_price=1200, purchase_date=date(2026, 1, 1),
        depreciation_method="straight_line", depreciation_annual_rate=20.0,
        depreciation_interval="monthly", depreciation_start_date=date(2026, 1, 1),
        depreciation_expense_account_id=expense.id, depreciation_asset_account_id=cash.id,
    )
    add(models.SimulationConfig, 6, user_id=client_id)
    registry = add(
        models.RegistryEntry, 7, name=marker, amount=100, budget_account_id=expense.id,
        source_account_id=cash.id, destination_account_id=expense.id,
        kind="expense", frequency="Monthly", repeat_mode="indefinite", start_date=date(2026, 1, 1), next_due_date=date(2026, 10, 31),
    )
    db.flush()
    batch = add(
        models.TransactionBatch, 10, label=marker,
        input_payload={"nested": {"account_id": cash.id, "life_event_id": goal.id}},
    )
    tx = add(
        models.Transaction, 11, date=date(2026, 10, 2), description=marker, amount_minor=100,
        batch_id=batch.id, registry_entry_id=registry.id,
    )
    db.flush()
    add(models.JournalEntry, 12, transaction_id=tx.id, account_id=expense.id, debit_minor=100, credit_minor=0, memo=marker, sort_order=0)
    add(models.JournalEntry, 13, transaction_id=tx.id, account_id=cash.id, debit_minor=0, credit_minor=100, memo=marker, sort_order=1, capsule_id=capsule.id)
    add(models.CapsuleDrawdown, 25, capsule_id=capsule.id, transaction_id=tx.id,
        kind="as_intended", amount_minor=100, note=marker)
    add(models.ProductDepreciation, 26, product_id=product.id, transaction_id=tx.id,
        period=PERIOD, amount_minor=50)
    plan = add(models.BudgetPlan, 14, name=marker, is_default=True, sort_order=20)
    add(
        models.MonthlyPlanLine, 15, plan_id=plan.id, target_period=PERIOD, line_type="expense",
        target_type="account", target_id=expense.id, account_id=expense.id,
        source_account_id=cash.id, name=marker, amount=100,
        identity_key=f"{marker}-expense",
    )
    add(models.PeriodClose, 26, period=PERIOD, closed_at=STAMP, note=marker)
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
        models.CapsuleRule, 19, capsule_id=capsule.id, trigger_type="expense",
        source_account_id=cash.id, destination_account_id=cash.id, amount_value=10,
    )
    add(
        models.CapsuleFundingSource, 24, client_id=client.id, capsule_id=capsule.id,
        account_id=cash.id, target_amount=250, max_share_bp=6000, sort_order=3,
    )
    capsule.goal_event_id = goal.id
    add(models.ExchangeRate, 22, base_currency="USD", quote_currency="JPY", rate=150, as_of_date=date(2026, 10, 1))
    db.flush()
    db.flush()
    add(models.ScenarioContributionPlan, 38, scenario_id=scenario.id, account_id=cash.id, start_period=PERIOD,
        monthly_amount_minor=30000, annual_return=3.0, note=marker)
    add(models.GoalBudgetReflection, 41, scenario_id=scenario.id, applied_at=STAMP, start_period="2026-10",
        end_period="2026-10", summary={"months": [{"period": "2026-10"}]})
    tracked = models.FxTrackedCurrency(client_id=client_id, currency="USD", created_at=STAMP)
    db.add(tracked)
    rows["fx_tracked_currencies"] = [tracked]
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
        assert {row.get("id", row.get("currency")) for row in exported} == {getattr(row, "id", getattr(row, "currency", None)) for row in rows[collection]}
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
    foreign_ids = {row.id for collection in other_rows.values() for row in collection if hasattr(row, "id")} | {other.id}

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
        assert {row.get("id", row.get("currency")) for row in exported} == {getattr(row, "id", getattr(row, "currency", None)) for row in rows[collection]}
    batch = document["data"]["transaction_batches"][0]
    assert batch["input_payload"]["nested"]["account_id"] == rows["accounts"][0].id
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
