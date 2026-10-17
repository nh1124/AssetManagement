from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.services.money_storage import minor_fields, rule_data
from app import models
from app.database import Base
from app.domain.errors import Invalid
from app.domain.transfer import DATA_COLLECTIONS, validate_import_payload
from app.services.data_transfer_service import export_client, import_client


STAMP = datetime(2026, 10, 1, 12)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def _client(db, client_id):
    client = models.Client(
        id=client_id, name=f"client-{client_id}", username=f"user-{client_id}",
        email=f"client-{client_id}@example.com", general_settings={"currency": "JPY"},
        ai_config={}, created_at=STAMP, updated_at=STAMP,
    )
    db.add(client)
    db.commit()
    return client


def _seed(db, client_id=101, base=10000):
    client = _client(db, client_id)
    rows = {}

    def add(model, offset, **values):
        values["id"] = base + offset
        if hasattr(model, "client_id"):
            values["client_id"] = client.id
        for field in ("created_at", "updated_at"):
            if hasattr(model, field):
                values[field] = STAMP
        money_names = {
            "monthly_plan_lines": ("amount",), "life_events": ("target_amount",),
            "milestones": ("target_amount",), "capsules": ("target_amount", "monthly_contribution"),
            "monthly_actions": ("amount",),
            "capsule_funding_sources": ("target_amount",),
            "products": ("last_unit_price", "purchase_price"), "simulation_configs": ("monthly_savings",),
            "simulation_scenarios": ("monthly_savings",), "life_scenarios": ("monthly_savings",), "registry_entries": ("amount",),
            "recurring_transactions": ("amount",),
        }
        if model.__tablename__ == "capsule_rules":
            values = rule_data(values, "JPY")
        elif model.__tablename__ in money_names:
            values = minor_fields(values, values.get("currency") or "JPY", *money_names[model.__tablename__])
        row = model(**values)
        db.add(row)
        db.flush()
        rows.setdefault(model.__tablename__, []).append(row)
        return row

    add(models.PeriodClose, 30, period="2026-10", closed_at=STAMP, note="reviewed")
    parent = add(models.Account, 1, name="assets", account_type="asset")
    cash = add(models.Account, 2, name="cash", account_type="asset",  parent_id=parent.id)
    expense = add(models.Account, 3, name="food", account_type="expense")
    scenario = add(models.LifeScenario, 36, name="保存案", annual_return=7.0, inflation=1.0, horizon_years=12, monthly_savings=30000, is_goal=True)
    db.flush()
    goal = add(models.LifeEvent, 4, scenario_id=scenario.id, name="goal", start_date=date(2026, 10, 1),
               target_date=date(2027, 1, 1), target_amount=1000, note="goal note", archived_at=STAMP)
    next_goal = add(models.LifeEvent, 31, scenario_id=scenario.id, name="next", target_date=date(2028, 1, 1), target_amount=500)
    add(models.LifeEventLink, 32, from_event_id=goal.id, to_event_id=next_goal.id,
        kind="after", offset_months=12, note="graph note")
    add(models.LifeScenarioAccountReturn, 38, scenario_id=scenario.id, account_id=cash.id, annual_return=3.0)
    capsule = add(models.Capsule, 5, name="goal", life_event_id=goal.id,
                  target_amount=1000, monthly_contribution=10,
                  capsule_type="life_event", target_amount_source="life_event")
    add(models.Capsule, 33, name="next", life_event_id=next_goal.id,
        target_amount=500, monthly_contribution=0,
        capsule_type="life_event", target_amount_source="life_event")
    member = add(models.HouseholdMember, 34, name="子", relation="長女", birth_date=date(2010, 4, 1))
    add(models.LifeEventCondition, 35, life_event_id=goal.id, metric="member_age", comparator="gte",
        threshold_number=18, reference_id=member.id, note="入学")
    product = add(models.Product, 6, name="food", category="expense", last_unit_price=100,
                  units_per_purchase=2, frequency_days=30, budget_account_id=expense.id,
                  funding_capsule_id=capsule.id, last_purchase_date=date(2026, 10, 2),
                  is_asset=True, lifespan_months=24, purchase_price=1200,
                  purchase_date=date(2026, 1, 1), depreciation_method="straight_line",
                  depreciation_annual_rate=20.0, depreciation_interval="monthly",
                  depreciation_start_date=date(2026, 1, 1),
                  depreciation_expense_account_id=expense.id,
                  depreciation_asset_account_id=cash.id)
    add(models.SimulationConfig, 7, user_id=client.id)
    registry = add(models.RegistryEntry, 8, name="food", amount=100, line_type="expense",
                   budget_account_id=expense.id, source_account_id=cash.id,
                   destination_account_id=expense.id, funding_capsule_id=capsule.id,
                   source_product_id=product.id, generate_recurring=True, note="registry note")
    recurring = add(models.RecurringTransaction, 9, name="food", amount=100, frequency="Monthly",
                    from_account_id=cash.id, to_account_id=expense.id,
                    source_registry_entry_id=registry.id, next_due_date=date(2026, 10, 31))
    registry.source_recurring_transaction_id = recurring.id
    template = add(models.QuickTemplate, 10, name="food", tray="expense", template_kind="simple",
                   default_from_account_id=cash.id, default_to_account_id=expense.id,
                   config={"nested": [{"account_id": cash.id, "capsule_id": capsule.id}]})
    batch = add(models.TransactionBatch, 11, quick_template_id=template.id, label="batch",
                input_payload={"nested": {"account_id": cash.id, "life_event_id": goal.id}})
    tx = add(models.Transaction, 12, date=date(2026, 10, 2), description="food", amount_minor=100,
             batch_id=batch.id, recurring_transaction_id=recurring.id)
    add(models.JournalEntry, 13, transaction_id=tx.id, account_id=expense.id,
        debit_minor=100, credit_minor=0, memo="debit", sort_order=0)
    add(models.JournalEntry, 14, transaction_id=tx.id, account_id=cash.id,
        debit_minor=0, credit_minor=100, memo="credit", sort_order=1, capsule_id=capsule.id)
    add(models.CapsuleDrawdown, 25, capsule_id=capsule.id, transaction_id=tx.id,
        kind="diverted", amount_minor=100, note="drawdown note")
    add(models.ProductDepreciation, 26, product_id=product.id, transaction_id=tx.id,
        period="2026-10", amount_minor=50)
    plan = add(models.BudgetPlan, 15, name="default", is_default=True, sort_order=10)
    line = add(models.MonthlyPlanLine, 16, plan_id=plan.id, target_period="2026-10",
               line_type="expense", target_type="account", target_id=expense.id,
               account_id=expense.id, source_account_id=cash.id, name="food", amount=100,
               identity_key=json.dumps([plan.id, "2026-10", "manual", "expense", "account",
                                        expense.id, cash.id, expense.id, "", "auto"], separators=(",", ":")))
    add(models.PeriodReview, 17, start_date=date(2026, 10, 1), end_date=date(2026, 11, 1),
        label="October", reflection="reflection", next_actions="actions")
    milestone = add(models.Milestone, 18, life_event_id=goal.id, date=date(2027, 1, 1),
                    target_amount=1000, note="milestone",
                    source_snapshot={"nested": {"account_id": cash.id}})
    add(models.CapsuleRule, 19, capsule_id=capsule.id, trigger_type="Expense",
        source_account_id=cash.id, destination_account_id=cash.id, amount_value=10)
    add(models.CapsuleFundingSource, 24, client_id=client.id, capsule_id=capsule.id,
        account_id=cash.id, target_amount=250, max_share_bp=6000, sort_order=3)
    add(models.SimulationScenario, 21, life_event_id=goal.id, name="scenario",
        annual_return=5, inflation=2, monthly_savings=10,
        contribution_schedule=[{"period": "2026-10", "amount": 10, "account_id": cash.id}])
    add(models.ExchangeRate, 22, base_currency="USD", quote_currency="JPY", rate=150,
        as_of_date=date(2026, 10, 1))
    add(models.MonthlyAction, 23, source_period="2026-10", target_period="2026-11",
        proposal_id="allocation", kind="boost_allocation", description="allocation",
        target_id=goal.id, idempotency_key="allocation", amount=10,
        payload={"nested": [{"account_id": cash.id, "life_event_id": goal.id,
                             "capsule_id": capsule.id, "product_id": product.id,
                             "recurring_id": recurring.id, "plan_id": plan.id,
                             "plan_line_id": line.id, "milestone_id": milestone.id}]},
        result={"nested": {"transaction_id": tx.id, "batch_id": batch.id,
                           "quick_template_id": template.id}}, status="applied", applied_at=STAMP)
    # Tables outside the backup format must survive a failed restore too,
    # including proposal links that a transaction deletion sets to NULL.
    add(models.TransactionProposal, 24, origin="test", date=date(2026, 10, 2),
        description="proposal", amount_minor=100, legs=[{"account_id": cash.id}],
        trigger_transaction_id=tx.id, posted_transaction_id=tx.id, idempotency_key="proposal")
    add(models.ClientMfaSetting, 25, enabled=False, totp_secret_encrypted="test-secret")
    add(models.ClientRecoveryCode, 26, code_hash="test-hash")
    add(models.AiOperationPolicy, 27, resource="data_transfer", action="import", risk="critical", mode="ask")
    add(models.AiAuditLog, 28, source="test", resource="data_transfer", action="import",
        risk="critical", decision="allowed", request_summary={"marker": "audit"})
    add(models.AiChangeRequest, 29, source="test", resource="transactions", action="create",
        risk="low", idempotency_key="change-request", target_ref={"account_id": cash.id})
    db.commit()
    return client, rows


def _table_bytes(db):
    return {
        name: json.dumps([dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()],
                         sort_keys=True, separators=(",", ":"), default=str).encode()
        for name, table in sorted(Base.metadata.tables.items())
    }


def _restore(db, client, document):
    return import_client(db, client, data=document["data"], version=document["version"], manifest=document["manifest"])


REFERENCES = {
    "scenario_id": "life_scenarios", "link_id": "life_event_links",
    "parent_id": "accounts", "account_id": "accounts", "from_account_id": "accounts",
    "to_account_id": "accounts", "source_account_id": "accounts", "destination_account_id": "accounts",
    "budget_account_id": "accounts", "default_from_account_id": "accounts", "default_to_account_id": "accounts",
    "source_product_id": "products", "product_id": "products", "source_registry_entry_id": "registry_entries",
    "source_recurring_transaction_id": "recurring_transactions", "recurring_transaction_id": "recurring_transactions",
    "recurring_id": "recurring_transactions", "quick_template_id": "quick_templates", "batch_id": "transaction_batches",
    "from_event_id": "life_events", "to_event_id": "life_events",
    "life_event_id": "life_events", "transaction_id": "transactions", "plan_id": "budget_plans",
    "plan_line_id": "monthly_plan_lines", "milestone_id": "milestones", "capsule_id": "capsules",
    "funding_capsule_id": "capsules",
    "depreciation_expense_account_id": "accounts",
    "depreciation_asset_account_id": "accounts",
}


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


def test_round_trip_preserves_every_collection_and_document(db):
    source, _ = _seed(db)
    target = _client(db, 202)
    original = export_client(db, source)
    assert list(original["data"]) == DATA_COLLECTIONS
    assert all(original["data"].values())
    result = _restore(db, target, original)
    restored = export_client(db, target)
    assert result["status"] == "ok"
    assert result["counts"] == original["manifest"]["counts"]
    assert result["validation"]["error_count"] == result["validation"]["warning_count"] == 0

    maps = {
        collection: {old["id"]: new["id"] for old, new in zip(old_rows, restored["data"][collection], strict=True)}
        for collection, old_rows in original["data"].items()
    }
    expected = copy.deepcopy(original)
    for collection, items in expected["data"].items():
        for item in items:
            item["id"] = maps[collection][item["id"]]
            for field, referenced_collection in REFERENCES.items():
                if item.get(field) is not None:
                    item[field] = maps[referenced_collection][item[field]]
            if collection == "life_event_conditions":
                item["reference_id"] = maps["household_members"][item["reference_id"]]
            if collection == "monthly_plan_lines":
                item["target_id"] = maps["accounts"][item["target_id"]]
                identity = json.loads(item["identity_key"])
                identity[0] = maps["budget_plans"][identity[0]]
                for index in (5, 6, 7):
                    identity[index] = maps["accounts"][identity[index]]
                item["identity_key"] = json.dumps(identity, separators=(",", ":"))
            if collection == "monthly_actions":
                item["target_id"] = maps["life_events"][item["target_id"]]
                for field, old_id in item["payload"]["nested"][0].items():
                    item["payload"]["nested"][0][field] = maps[REFERENCES[field]][old_id]
                for field, old_id in item["result"]["nested"].items():
                    item["result"]["nested"][field] = maps[REFERENCES[field]][old_id]

    # Reconnecting the registry's recurring and capsule links triggers the
    # existing ORM onupdate timestamp; this is not an import-time rewrite.
    # It fires on whichever side the flush happens to touch, so comparing the
    # two exports against each other is a race -- it failed about once in five
    # full runs. Both are bounded below by the seeded stamp, which is what
    # actually says the timestamp was not zeroed or moved backwards.
    new_registry = restored["data"]["registry_entries"][0]
    assert datetime.fromisoformat(new_registry["updated_at"]) >= STAMP
    expected["data"]["registry_entries"][0]["updated_at"] = new_registry["updated_at"]
    # Restore targets the authenticated client and never restores its identity
    # or settings. Hashes necessarily change with remapped IDs and timestamps.
    assert restored["client"] == {
        "id": target.id, "name": target.name, "username": target.username,
        "email": target.email, "general_settings": target.general_settings,
    }
    expected["client"] = restored["client"]
    expected["exported_at"] = restored["exported_at"]
    expected["manifest"]["client_id"] = target.id
    expected["manifest"]["exported_at"] = restored["exported_at"]
    # Health is derived from the restored rows, so its references name the
    # destination IDs too. F3 makes this fixture's plan mismatch and share
    # warnings visible; keep comparing their full contents after remapping.
    def remap_health(value):
        if isinstance(value, list):
            return [remap_health(item) for item in value]
        if isinstance(value, dict):
            return {
                key: maps[REFERENCES[key]][item] if key in REFERENCES and item is not None
                else remap_health(item)
                for key, item in value.items()
            }
        return value

    expected["health"] = remap_health(expected["health"])
    checksums = {key: _checksum(value) for key, value in expected["data"].items()}
    expected["manifest"]["checksums"] = checksums
    expected["manifest"]["payload_checksum"] = _checksum({"data": expected["data"], "checksums": checksums})
    assert restored == expected
    # These JSON fields are opaque in the established format, unlike action
    # payload/result. Their embedded source IDs must remain byte-for-byte.
    for collection, field in (("quick_templates", "config"), ("transaction_batches", "input_payload"),
                              ("milestones", "source_snapshot"), ("simulation_scenarios", "contribution_schedule")):
        assert restored["data"][collection][0][field] == original["data"][collection][0][field]


def test_journal_failure_after_deletion_preserves_every_table_byte_for_byte(db):
    client, _ = _seed(db)
    # A second client, so this still proves rollback preserves every table,
    # including an unrelated client's rows. The plan is in the transfer format
    # now, and the fixture seeds one for each client.
    _seed(db, client_id=102, base=20000)
    document = export_client(db, client)
    document["data"]["journal_entries"][0]["account_id"] = str(document["data"]["journal_entries"][0]["account_id"])
    assert validate_import_payload(document["data"], document["version"], document["manifest"])["error_count"] == 0
    before = _table_bytes(db)
    assert all(json.loads(value) for value in before.values())
    with pytest.raises(Invalid) as caught:
        _restore(db, client, document)
    assert str(caught.value).startswith("Import failed: Transaction ")
    assert str(caught.value).endswith(" has fewer than two journal entries")
    assert _table_bytes(db) == before


def test_validation_gate_keeps_exact_400_detail_and_writes_nothing(db):
    client, _ = _seed(db)
    document = export_client(db, client)
    document["data"]["journal_entries"] = []
    validation = validate_import_payload(document["data"], document["version"], document["manifest"])
    assert validation["error_count"] > 0
    before = _table_bytes(db)
    writes = []

    def capture(_, __, statement, ___, ____, _____):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        with pytest.raises(Invalid) as caught:
            _restore(db, client, document)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    assert str(caught.value) == "Import payload validation failed"
    assert caught.value.payload == {"message": "Import payload validation failed", "validation": validation}
    assert writes == []
    assert _table_bytes(db) == before


def test_colliding_ids_are_remapped_without_touching_the_other_client(db):
    other, _ = _seed(db)
    target = _client(db, 202)
    document = export_client(db, other)
    before = {name: json.loads(value) for name, value in _table_bytes(db).items()}
    _restore(db, target, document)
    restored = export_client(db, target)
    for collection in DATA_COLLECTIONS:
        assert len(restored["data"][collection]) == len(document["data"][collection])
        assert {row["id"] for row in restored["data"][collection]}.isdisjoint(
            row["id"] for row in document["data"][collection]
        ), collection
    after = {name: json.loads(value) for name, value in _table_bytes(db).items()}
    for table, original_rows in before.items():
        by_id = {row["id"]: row for row in after[table]}
        assert [by_id[row["id"]] for row in original_rows] == original_rows, table
    assert export_client(db, other)["data"] == document["data"]


def test_successful_import_balances_the_whole_journal(db):
    source, _ = _seed(db)
    target = _client(db, 202)
    _restore(db, target, export_client(db, source))
    count, debit, credit = db.query(func.count(models.JournalEntry.id), func.sum(models.JournalEntry.debit),
                                  func.sum(models.JournalEntry.credit)).one()
    assert count == 4
    assert debit == credit == 200


def test_commit_failure_rolls_back_the_complete_rebuild(db):
    client, _ = _seed(db)
    document = export_client(db, client)
    before = _table_bytes(db)
    commits = []

    def fail_commit(session):
        commits.append(session)
        assert db.query(models.MonthlyAction).filter_by(client_id=client.id).count() == 1
        raise RuntimeError("commit refused")

    event.listen(db, "before_commit", fail_commit)
    try:
        with pytest.raises(Invalid) as caught:
            _restore(db, client, document)
    finally:
        event.remove(db, "before_commit", fail_commit)
    assert commits == [db]
    assert str(caught.value) == "Import failed: commit refused"
    assert _table_bytes(db) == before
