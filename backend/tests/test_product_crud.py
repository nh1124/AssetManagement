from app.services.money_storage import to_minor

from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.database import Base
from app.services import product_service, registry_service
from app.workflows import product_workflow
from product_saves import confirmed


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add(models.Client(id=1, name="Product CRUD", general_settings={}))
        session.commit()
        yield session
    engine.dispose()


def _payload(**changes):
    return schemas.ProductCreate(**{
        "name": "Water filter", "last_unit_price": 6000, "frequency_days": 180,
        **changes,
    })


def test_product_create_keeps_automatic_transactions_separate(db):
    confirmed(product_workflow.create_product, db, 1, _payload())
    assert db.query(models.Product).count() == 1
    assert db.query(models.RegistryEntry).count() == 0


def test_product_funding_link_stays_single_and_same_through_put_and_patch(db):
    product = confirmed(product_workflow.create_product, db, 1, _payload())
    product_id, capsule_id = product.id, product.funding_capsule_id
    capsules_before = db.query(models.Capsule).count()
    assert capsules_before == 2
    capsule_before = db.execute(models.Capsule.__table__.select()).all()

    updated = confirmed(product_workflow.update_product, db, 1, product_id, _payload(last_unit_price=9000, funding_capsule_id=capsule_id),
    )
    assert updated.funding_capsule_id == capsule_id
    patched = confirmed(product_workflow.patch_product, db, 1, product_id, schemas.ProductUpdate(last_unit_price=12000),
    )
    assert patched.funding_capsule_id == capsule_id
    assert patched.last_unit_price == 12000
    assert db.query(models.Product).one().funding_capsule_id == capsule_id
    assert db.query(models.Capsule).count() == capsules_before
    # The link stays; the capsule's amounts follow the product (12,000 every 180 days).
    pool = db.get(models.Capsule, capsule_id)
    assert (pool.target_amount, pool.monthly_contribution) == (12000, 2000)
    assert [row.id for row in db.execute(models.Capsule.__table__.select()).all()] == [row.id for row in capsule_before]


def test_delete_product_keeps_its_capsule(db):
    product = confirmed(product_workflow.create_product, db, 1, _payload())
    product_id, capsule_id = product.id, product.funding_capsule_id
    assert confirmed(product_workflow.delete_product, db, 1, product_id)
    assert db.get(models.Product, product_id) is None
    pool = db.get(models.Capsule, capsule_id)
    assert (pool.target_amount, pool.monthly_contribution) == (6000, 1000)
    assert pool.target_amount_source == pool.monthly_contribution_source == "manual"
    assert db.query(models.RegistryEntry).count() == 0


def test_product_reads_are_client_scoped_and_preserve_unit_economics(db):
    product = confirmed(product_workflow.create_product, db, 1, _payload(name="Coffee", category="Grocery", frequency_days=30, units_per_purchase=2),
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
