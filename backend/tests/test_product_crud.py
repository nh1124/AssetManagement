from app.services.money_storage import to_minor

from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.services import product_service, registry_service
from app.workflows import product_workflow


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add(models.Client(id=1, name="Product CRUD", general_settings={}, ai_config={}))
        session.commit()
        yield session
    engine.dispose()


def _payload(**changes):
    return schemas.ProductCreate(**{
        "name": "Water filter", "last_unit_price": 6000, "frequency_days": 180,
        **changes,
    })


def test_product_create_defers_registry_sync_and_repeated_sync_creates_one_entry_per_product_identity(db):
    product = product_workflow.create_product(db, 1, _payload())
    assert db.query(models.Product).count() == 1
    assert db.query(models.RegistryEntry).count() == 0
    first = registry_service.sync_registry_from_product(db, product)
    db.commit()
    first_id = first.id
    second = registry_service.sync_registry_from_product(db, product)
    db.commit()
    assert second.id == first_id
    assert db.query(models.RegistryEntry).count() == 1
    assert (second.source_product_id, second.funding_capsule_id) == (product.id, product.funding_capsule_id)


def test_product_funding_link_stays_single_and_same_through_put_and_patch(db):
    product = product_workflow.create_product(db, 1, _payload())
    product_id, capsule_id = product.id, product.funding_capsule_id
    capsules_before = db.query(models.Capsule).count()
    assert capsules_before == 2
    capsule_before = db.execute(models.Capsule.__table__.select()).all()

    updated = product_workflow.update_product(
        db, 1, product_id, _payload(last_unit_price=9000, funding_capsule_id=capsule_id),
    )
    assert updated.funding_capsule_id == capsule_id
    patched = product_workflow.patch_product(
        db, 1, product_id, schemas.ProductUpdate(last_unit_price=12000),
    )
    assert patched.funding_capsule_id == capsule_id
    assert patched.last_unit_price == 12000
    assert db.query(models.Product).one().funding_capsule_id == capsule_id
    assert db.query(models.Capsule).count() == capsules_before
    # CRUD keeps the link; the explicit reserve-sync endpoint owns aggregation.
    assert db.execute(models.Capsule.__table__.select()).all() == capsule_before


@pytest.mark.parametrize("has_registry", [False, True])
def test_delete_product_deactivates_and_detaches_registry_but_keeps_capsules_and_recurring(db, has_registry):
    product = product_workflow.create_product(db, 1, _payload())
    product_id = product.id
    if has_registry:
        entry = registry_service.sync_registry_from_product(db, product)
        db.flush()
        recurring = models.RecurringTransaction(
            client_id=1, name="Existing recurrence", amount_minor=to_minor(123, "JPY"), frequency="Monthly",
            source_registry_entry_id=entry.id, next_due_date=date(2026, 11, 1),
        )
        db.add(recurring)
        db.flush()
        entry.generate_recurring = True
        entry.budget_active = True
        entry.source_recurring_transaction_id = recurring.id
        db.commit()
        entry_id = entry.id
    capsules_before = db.execute(models.Capsule.__table__.select()).all()
    recurring_before = db.execute(models.RecurringTransaction.__table__.select()).all()

    assert product_workflow.delete_product(db, 1, product_id)
    db.expire_all()
    assert db.get(models.Product, product_id) is None
    assert db.execute(models.Capsule.__table__.select()).all() == capsules_before
    assert db.execute(models.RecurringTransaction.__table__.select()).all() == recurring_before
    if has_registry:
        entry = db.get(models.RegistryEntry, entry_id)
        assert entry is not None
        assert (entry.is_active, entry.budget_active, entry.source_product_id) == (False, False, None)
        assert entry.generate_recurring is True
        assert entry.source_recurring_transaction_id == recurring_before[0].id
        assert entry.funding_capsule_id is not None
    else:
        assert db.query(models.RegistryEntry).count() == 0


def test_product_reads_are_client_scoped_and_preserve_unit_economics(db):
    product = product_workflow.create_product(
        db, 1, _payload(name="Coffee", category="Grocery", frequency_days=30, units_per_purchase=2),
    )
    assert product_service.get_product(db, 2, product.id) is None
    assert product_service.list_products(db, 2) == []
    assert product_service.list_products(db, 1, category="Grocery", is_asset=False) == [product]
    assert product_service.list_products(db, 1, category="Other") == []
    assert product_service.enrich_product(product)["monthly_cost"] == 3000
    assert product_service.get_unit_economics_summary(db, 1) == {
        "items": [{"name": "Coffee", "category": "Grocery", "unit_cost": 3000, "monthly_cost": 3000}],
        "category_breakdown": [{"category": "Grocery", "monthly_cost": 3000}],
        "total_monthly_cost": 3000,
    }
