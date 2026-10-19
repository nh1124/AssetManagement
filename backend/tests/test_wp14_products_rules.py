"""WP14: journal account filters, portable rules, and enabling depreciation."""
from copy import deepcopy
from datetime import date
import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import Base
from app.domain.errors import Invalid, NotFound
from app.domain.transfer import EXPORT_VERSION, validate_import_payload
from app.routers.capsules import _rule_to_dict
from app.services import capsule_service as capsules, data_transfer_service as transfer
from app.workflows import product_workflow as products


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite:///:memory:")
    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        session.add_all([models.Client(id=i, name=f"test-{i}", general_settings={"currency": "JPY"}) for i in (1, 2)])
        session.flush()
        session.add_all([models.Account(id=i, client_id=2 if i == 7 else 1, name=f"account-{i}", account_type=kind)
                         for i, kind in enumerate(["asset", "asset", "income", "expense", "liability", "expense", "asset"], 1)])
        session.commit()
        yield session
    engine.dispose()


def rule(db, **changes):
    owner = capsules.create_capsule(db, 1, schemas.CapsuleCreate(
        name="reserve", account_id=2, target_amount=10000, monthly_contribution=0,
    ))
    return capsules.create_rule(db, 1, schemas.CapsuleRuleCreate(**{
        "capsule_id": owner.id, "trigger_type": "Income", "amount_value": 10,
        "source_mode": "fixed_account", "source_account_id": 1, **changes,
    }))


def preview(db):
    return capsules.capsule_transfer_specs(db, 1, entries=[
        schemas.TransactionLeg(account_id=1, debit=100), schemas.TransactionLeg(account_id=3, credit=100),
        schemas.TransactionLeg(account_id=4, debit=20), schemas.TransactionLeg(account_id=5, credit=20),
    ], description="payment", amount=120, currency="JPY")


@pytest.mark.parametrize("account_id, fires", [(None, True), (1, True), (3, True), (4, True), (5, True), (6, False)])
def test_trigger_can_match_any_journal_leg_and_any_account_type(db, account_id, fires):
    saved = rule(db, trigger_account_id=account_id)
    assert bool(preview(db)) is fires
    assert _rule_to_dict(saved)["trigger_account_id"] == account_id


def test_trigger_condition_can_be_replaced_cleared_and_disabled(db):
    saved = rule(db, trigger_account_id=6)
    assert not preview(db)
    capsules.update_rule(db, 1, saved.id, schemas.CapsuleRuleUpdate(trigger_account_id=3))
    assert preview(db)
    capsules.update_rule(db, 1, saved.id, schemas.CapsuleRuleUpdate(trigger_description="absent"))
    assert not preview(db)  # Conditions combine, rather than replacing the existing trigger.
    capsules.update_rule(db, 1, saved.id, schemas.CapsuleRuleUpdate(trigger_account_id=None, trigger_description=None, is_active=False))
    assert saved.trigger_account_id is None
    assert not preview(db)


@pytest.mark.parametrize("account_id", [7, 999, 0])
def test_create_and_update_reject_foreign_or_missing_trigger_account(db, account_id):
    saved = rule(db)
    with pytest.raises(NotFound):
        capsules.update_rule(db, 1, saved.id, schemas.CapsuleRuleUpdate(trigger_account_id=account_id))
    with pytest.raises(NotFound):
        capsules.create_rule(db, 1, schemas.CapsuleRuleCreate(capsule_id=saved.capsule_id, trigger_type="Income", amount_value=1, trigger_account_id=account_id))
    assert saved.trigger_account_id is None
    assert capsules.update_rule(db, 2, saved.id, schemas.CapsuleRuleUpdate(trigger_account_id=None)) is None


def test_deleting_trigger_account_preserves_rule_and_clears_condition(db):
    saved = rule(db, trigger_account_id=6)
    db.delete(db.get(models.Account, 6))
    db.commit()
    db.refresh(saved)
    assert saved.trigger_account_id is None
    assert preview(db)


@pytest.mark.parametrize("version", [24, 25])
def test_backup_remaps_trigger_reference_and_old_backup_defaults_to_unfiltered(db, version):
    rule(db, trigger_account_id=3)
    document = transfer.export_client(db, db.get(models.Client, 1))
    assert document["version"] == EXPORT_VERSION == 28
    assert document["data"]["capsule_rules"][0]["trigger_account_id"] == 3
    data = deepcopy(document["data"])
    if version == 24:
        for row in data["capsule_rules"]:
            del row["trigger_account_id"]
    transfer.import_client(db, db.get(models.Client, 2), data=data, version=version, manifest=None)
    imported = db.query(models.CapsuleRule).filter_by(client_id=2).one()
    if version == 24:
        assert imported.trigger_account_id is None
    else:
        account = db.get(models.Account, imported.trigger_account_id)
        assert account.client_id == 2 and account.name == "account-3" and account.id != 3


def test_backup_rejects_a_dangling_trigger_reference(db):
    rule(db, trigger_account_id=3)
    data = transfer.export_client(db, db.get(models.Client, 1))["data"]
    data["capsule_rules"][0]["trigger_account_id"] = 999
    result = validate_import_payload(data, 25)
    assert any(issue.get("field") == "trigger_account_id" and issue["severity"] == "error" for issue in result["issues"])


def asset(**changes):
    return schemas.ProductCreate(**{
        "name": "equipment", "last_unit_price": 1200, "is_asset": True,
        "budget_treatment": "expense_only", "purchase_price": 1200, "purchase_date": date(2026, 1, 1),
        "lifespan_months": 12, "depreciation_method": "straight_line", "depreciation_interval": "monthly",
        "depreciation_expense_account_id": 4, "depreciation_asset_account_id": 1, **changes,
    })


@pytest.mark.parametrize("write", ["put", "patch", "create"])
def test_enabling_depreciation_posts_ended_periods_once(db, monkeypatch, write):
    monkeypatch.setattr(products.registry_service, "client_today", lambda *_: date(2026, 3, 15))
    saved = products.create_product(db, 1, asset(auto_depreciation=write == "create"))
    if write == "put":
        products.update_product(db, 1, saved.id, asset(auto_depreciation=True))
    elif write == "patch":
        products.patch_product(db, 1, saved.id, schemas.ProductUpdate(auto_depreciation=True))
    rows = db.query(models.ProductDepreciation).order_by(models.ProductDepreciation.period).all()
    assert [(r.period, r.amount_minor) for r in rows] == [("2026-01", 100), ("2026-02", 100)]
    assert [db.get(models.Transaction, r.transaction_id).date for r in rows] == [date(2026, 1, 31), date(2026, 2, 28)]
    products.update_product(db, 1, saved.id, asset(auto_depreciation=True))
    products.patch_product(db, 1, saved.id, schemas.ProductUpdate(auto_depreciation=False))
    assert db.query(models.ProductDepreciation).count() == 2
    assert db.query(models.JournalEntry).count() == 4
    assert all(sum(j.debit_minor for j in tx.journal_entries) == sum(j.credit_minor for j in tx.journal_entries) == tx.amount_minor
               for tx in db.query(models.Transaction))


@pytest.mark.parametrize("changes", [
    {"depreciation_method": "none"}, {"depreciation_expense_account_id": None}, {"depreciation_asset_account_id": None},
    {"depreciation_asset_account_id": 7}, {"purchase_date": None}, {"lifespan_months": None},
    {"purchase_price": None}, {"depreciation_method": "declining_balance", "depreciation_annual_rate": 0},
])
def test_automatic_depreciation_requires_settings_even_for_future_periods(db, changes):
    saved = products.create_product(db, 1, asset(**changes))  # Off keeps the book-value method independently.
    with pytest.raises(Invalid):
        products.patch_product(db, 1, saved.id, schemas.ProductUpdate(auto_depreciation=True))
    db.rollback()
    assert not db.get(models.Product, saved.id).auto_depreciation
    assert db.query(models.Transaction).count() == 0


def migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261019_0077_capsule_rule_trigger_account.py"
    spec = importlib.util.spec_from_file_location("wp14", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_rules_and_set_null_foreign_key():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE capsule_rules (id INTEGER PRIMARY KEY, amount_minor BIGINT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO accounts VALUES (1)")
        connection.exec_driver_sql("INSERT INTO capsule_rules VALUES (10, 1234)")
        for direction in ("upgrade", "downgrade", "upgrade"):
            with Operations.context(MigrationContext.configure(connection)):
                getattr(migration(), direction)()
            assert connection.scalar(sa.text("SELECT amount_minor FROM capsule_rules WHERE id=10")) == 1234
            if direction == "upgrade":
                assert connection.scalar(sa.text("SELECT trigger_account_id FROM capsule_rules")) is None
        connection.exec_driver_sql("UPDATE capsule_rules SET trigger_account_id=1")
        connection.exec_driver_sql("DELETE FROM accounts WHERE id=1")
        assert connection.scalar(sa.text("SELECT trigger_account_id FROM capsule_rules")) is None
    engine.dispose()


def test_migration_generates_postgresql_set_null_sql():
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration().upgrade()
    sql = output.getvalue()
    assert "ADD COLUMN trigger_account_id INTEGER" in sql
    assert "FOREIGN KEY(trigger_account_id) REFERENCES accounts (id) ON DELETE SET NULL" in sql
