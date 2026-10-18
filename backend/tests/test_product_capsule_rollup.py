from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, schemas
from app.database import Base, get_db
from app.dependencies import get_current_client
from app.domain.errors import Conflict, DomainError, Invalid, detail_for, status_for
from app.routers.products import router
from app.services import product_service
from app.services.money_storage import money_client_currency, to_minor
from app.services.product_reserve_service import refresh_product_capsules
from app.workflows import product_workflow
from product_saves import confirmed


@pytest.fixture
def db():
    # One shared connection, so the HTTP test's worker thread sees the same database.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False)() as session:
        session.add_all([
            models.Client(id=1, name="Product reserves", general_settings={"currency": "JPY"}),
            models.Client(id=2, name="Other client", general_settings={"currency": "JPY"}),
        ])
        session.commit()
        yield session
    engine.dispose()


def _capsule(db, client_id=1):
    currency = money_client_currency(db, client_id)
    capsule = models.Capsule(
        client_id=client_id, name="Product reserve",
        target_amount_minor=to_minor(1234, currency),
        monthly_contribution_minor=to_minor(56, currency),
    )
    db.add(capsule)
    db.commit()
    return capsule


def _payload(capsule_id, **changes):
    return schemas.ProductCreate(**{
        "name": "Water filter", "last_unit_price": 6000, "frequency_days": 180,
        "funding_capsule_id": capsule_id, **changes,
    })


def _assert_rollup(db, capsule, target, monthly, source="linked_products"):
    db.refresh(capsule)
    assert capsule.capsule_type == "product_pool"
    assert capsule.target_amount_source == capsule.monthly_contribution_source == source
    currency = money_client_currency(db, capsule.client_id)
    assert capsule.target_amount_minor == to_minor(target, currency)
    assert capsule.monthly_contribution_minor == to_minor(monthly, currency)
    assert capsule.target_amount == target
    assert capsule.monthly_contribution == monthly


@pytest.mark.parametrize("currency", ["JPY", "USD"])
def test_create_consumables_sums_reserves_in_client_currency(db, currency):
    db.get(models.Client, 1).general_settings = {"currency": currency}
    capsule = _capsule(db)
    confirmed(product_workflow.create_product, db, 1, _payload(capsule.id))
    confirmed(product_workflow.create_product, db, 1, _payload(
        capsule.id, name="Filter pack", last_unit_price=12000,
        units_per_purchase=2, frequency_days=90,
    ))

    _assert_rollup(db, capsule, 18000, 3000)
    assert refresh_product_capsules(db, 1, [None, capsule.id, capsule.id, -1]) == [{
        "capsule_id": capsule.id, "products": 2,
        "target_amount": 18000.0, "monthly_contribution": 3000.0,
    }]


@pytest.mark.parametrize("partial", [False, True])
def test_move_product_refreshes_both_capsules(db, partial):
    previous, destination = _capsule(db), _capsule(db)
    confirmed(product_workflow.create_product, db, 1, _payload(previous.id))
    moving = confirmed(product_workflow.create_product, db, 1, _payload(previous.id, last_unit_price=12000))
    confirmed(product_workflow.create_product, db, 1, _payload(destination.id, last_unit_price=3000, frequency_days=90))

    if partial:
        confirmed(product_workflow.patch_product, db, 1, moving.id, schemas.ProductUpdate(funding_capsule_id=destination.id))
    else:
        confirmed(product_workflow.update_product, db, 1, moving.id, _payload(destination.id, last_unit_price=12000))

    _assert_rollup(db, previous, 6000, 1000)
    _assert_rollup(db, destination, 15000, 3000)


def test_delete_last_product_releases_sources_and_keeps_amounts(db):
    capsule = _capsule(db)
    product = confirmed(product_workflow.create_product, db, 1, _payload(capsule.id))

    assert confirmed(product_workflow.delete_product, db, 1, product.id)

    _assert_rollup(db, capsule, 6000, 1000, source="manual")
    assert refresh_product_capsules(db, 1, [capsule.id]) == [{
        "capsule_id": capsule.id, "products": 0,
        "target_amount": 6000.0, "monthly_contribution": 1000.0,
    }]


def test_expense_only_products_do_not_contribute_even_with_existing_links(db):
    capsule = _capsule(db)
    confirmed(product_workflow.create_product, db, 1, _payload(capsule.id))
    expense = confirmed(product_workflow.create_product, db, 1, _payload(capsule.id, budget_treatment="expense_only"))
    assert expense.funding_capsule_id is None
    # Older records may retain a funding link despite their expense treatment.
    product_service.update_product(db, 1, expense.id, {"funding_capsule_id": capsule.id}, commit=False)

    result = refresh_product_capsules(db, 1, [capsule.id])

    assert result[0]["products"] == 1
    _assert_rollup(db, capsule, 6000, 1000)


@pytest.mark.parametrize("partial", [False, True])
def test_updating_to_expense_only_releases_previous_capsule(db, partial):
    capsule = _capsule(db)
    product = confirmed(product_workflow.create_product, db, 1, _payload(capsule.id))

    if partial:
        confirmed(product_workflow.patch_product, db, 1, product.id, schemas.ProductUpdate(budget_treatment="expense_only"))
    else:
        confirmed(product_workflow.update_product, db, 1, product.id, _payload(capsule.id, budget_treatment="expense_only"))

    assert product.funding_capsule_id is None
    _assert_rollup(db, capsule, 6000, 1000, source="manual")


def test_refresh_is_scoped_to_capsule_and_product_client(db):
    local, foreign = _capsule(db), _capsule(db, client_id=2)
    confirmed(product_workflow.create_product, db, 1, _payload(local.id))
    other = confirmed(product_workflow.create_product, db, 2, _payload(foreign.id, last_unit_price=12000))
    # Even a malformed cross-client link must not affect this client's totals.
    product_service.update_product(db, 2, other.id, {"funding_capsule_id": local.id}, commit=False)

    result = refresh_product_capsules(db, 1, [local.id, foreign.id, None, -1])

    assert [row["capsule_id"] for row in result] == [local.id]
    assert result[0]["products"] == 1
    _assert_rollup(db, local, 6000, 1000)
    _assert_rollup(db, foreign, 12000, 2000)
    with pytest.raises(Invalid):
        confirmed(product_workflow.create_product, db, 1, _payload(foreign.id))
    _assert_rollup(db, foreign, 12000, 2000)


def test_asset_and_partial_price_update_refresh_reserves(db):
    capsule = _capsule(db)
    product = confirmed(product_workflow.create_product, db, 1, _payload(
        capsule.id, is_asset=True, purchase_price=120000, lifespan_months=24,
    ))
    _assert_rollup(db, capsule, 120000, 5000)

    confirmed(product_workflow.patch_product, db, 1, product.id, schemas.ProductUpdate(purchase_price=240000))

    _assert_rollup(db, capsule, 240000, 10000)


def test_create_and_rollup_share_the_callers_transaction(db):
    capsule = _capsule(db)
    product = confirmed(product_workflow.create_product, db, 1, _payload(capsule.id), commit=False)
    product_id = product.id
    _assert_rollup(db, capsule, 6000, 1000)

    db.rollback()

    assert db.get(models.Product, product_id) is None
    db.refresh(capsule)
    assert capsule.target_amount_source == capsule.monthly_contribution_source == "manual"
    assert (capsule.target_amount, capsule.monthly_contribution) == (1234, 56)


def _refusal(save, db, *args, **kwargs):
    with pytest.raises(Conflict) as refused:
        save(db, *args, **kwargs)
    db.rollback()
    assert refused.value.payload["code"] == "reserve_changes_unconfirmed"
    return refused.value.payload


def test_a_save_that_moves_an_earmark_is_refused_until_confirmed(db):
    capsule = _capsule(db)

    refusal = _refusal(product_workflow.create_product, db, 1, _payload(capsule.id))

    assert refusal["changes"] == [{
        "capsule_id": capsule.id, "name": "Product reserve",
        "target_before": 1234.0, "target_after": 6000.0, "monthly_before": 56.0, "monthly_after": 1000.0,
    }]
    assert db.query(models.Product).count() == 0
    db.refresh(capsule)
    assert (capsule.capsule_type, capsule.target_amount, capsule.monthly_contribution) == ("manual", 1234, 56)
    product_workflow.create_product(db, 1, _payload(capsule.id), reserve_fingerprint=refusal["fingerprint"])
    _assert_rollup(db, capsule, 6000, 1000)


def test_a_stale_confirmation_is_refused_again(db):
    capsule = _capsule(db)
    stale = _refusal(product_workflow.create_product, db, 1, _payload(capsule.id))["fingerprint"]
    confirmed(product_workflow.create_product, db, 1, _payload(capsule.id, name="Other filter"))

    refusal = _refusal(product_workflow.create_product, db, 1, _payload(capsule.id), reserve_fingerprint=stale)

    assert refusal["fingerprint"] != stale
    assert refusal["changes"][0]["target_before"] == 6000.0
    assert db.query(models.Product).count() == 1


def test_a_save_that_leaves_earmarks_unchanged_needs_no_confirmation(db):
    capsule = _capsule(db)
    product = confirmed(product_workflow.create_product, db, 1, _payload(capsule.id))

    product_workflow.update_product(db, 1, product.id, _payload(capsule.id, name="Renamed filter"))
    product_workflow.create_product(db, 1, _payload(None, name="Tissues", frequency_days=30))

    assert db.get(models.Product, product.id).name == "Renamed filter"
    _assert_rollup(db, capsule, 6000, 1000)


def test_patch_and_delete_are_confirmed_as_well(db):
    capsule = _capsule(db)
    product = confirmed(product_workflow.create_product, db, 1, _payload(capsule.id))
    confirmed(product_workflow.create_product, db, 1, _payload(capsule.id, name="Second filter"))

    patched = _refusal(product_workflow.patch_product, db, 1, product.id, schemas.ProductUpdate(last_unit_price=12000))
    assert (patched["changes"][0]["monthly_before"], patched["changes"][0]["monthly_after"]) == (2000.0, 3000.0)
    deleted = _refusal(product_workflow.delete_product, db, 1, product.id)
    assert (deleted["changes"][0]["target_before"], deleted["changes"][0]["target_after"]) == (12000.0, 6000.0)
    assert db.get(models.Product, product.id) is not None

    assert product_workflow.delete_product(db, 1, product.id, reserve_fingerprint=deleted["fingerprint"])
    _assert_rollup(db, capsule, 6000, 1000)


def test_http_save_returns_the_changes_and_accepts_the_fingerprint(db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_client] = lambda: db.get(models.Client, 1)

    @app.exception_handler(DomainError)
    async def domain_error(_, error):
        return JSONResponse(status_code=status_for(error), content={"detail": detail_for(error)})

    capsule = _capsule(db)
    body = _payload(capsule.id).model_dump(mode="json")

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            refused = await client.post("/products/", json=body)
            db.rollback()
            fingerprint = refused.json()["detail"]["fingerprint"]
            saved = await client.post("/products/", json=body, params={"reserve_fingerprint": fingerprint})
            return refused, saved

    refused, saved = asyncio.run(run())

    assert refused.status_code == 409
    assert refused.json()["detail"]["changes"][0]["target_after"] == 6000.0
    assert saved.status_code == 200
    _assert_rollup(db, capsule, 6000, 1000)
