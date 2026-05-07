from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.product_reserve_service import (
        ensure_default_product_reserve_pools,
        product_reserve_values,
        sync_product_reserve_capsules,
    )
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.product_reserve_service import (  # type: ignore[no-redef]
        ensure_default_product_reserve_pools,
        product_reserve_values,
        sync_product_reserve_capsules,
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_product_reserve_values_for_asset_and_item() -> None:
    asset = models.Product(
        client_id=1,
        name="Laptop",
        category="Electronics",
        last_unit_price=120000,
        is_asset=True,
        purchase_price=120000,
        purchase_date=date(2026, 1, 1),
        lifespan_months=24,
    )
    item = models.Product(
        client_id=1,
        name="Coffee beans",
        category="Grocery",
        last_unit_price=3000,
        units_per_purchase=1,
        frequency_days=30,
        is_asset=False,
    )

    assert product_reserve_values(asset, reference_date=date(2026, 1, 1)) == {
        "reserve_target_amount": 120000,
        "recommended_monthly_reserve": 5000,
    }
    assert product_reserve_values(item, reference_date=date(2026, 1, 1)) == {
        "reserve_target_amount": 3000,
        "recommended_monthly_reserve": 3000,
    }


def test_sync_product_reserve_capsules_rolls_up_linked_products() -> None:
    db = _session()
    try:
        db.add(models.Client(id=1, name="test", general_settings={}, ai_config={}))
        pools = ensure_default_product_reserve_pools(db, client_id=1)
        fixed_pool = next(pool for pool in pools if pool.name == "Fixed Asset Reserve")
        item_pool = next(pool for pool in pools if pool.name == "Item Reserve")
        db.add_all([
            models.Product(
                client_id=1,
                name="Laptop",
                category="Electronics",
                last_unit_price=120000,
                is_asset=True,
                purchase_price=120000,
                purchase_date=date(2026, 1, 1),
                lifespan_months=24,
                funding_capsule_id=fixed_pool.id,
            ),
            models.Product(
                client_id=1,
                name="Coffee beans",
                category="Grocery",
                last_unit_price=3000,
                units_per_purchase=1,
                frequency_days=30,
                is_asset=False,
                funding_capsule_id=item_pool.id,
            ),
        ])
        db.commit()

        result = sync_product_reserve_capsules(db, client_id=1)
        db.commit()
        db.refresh(fixed_pool)
        db.refresh(item_pool)

        assert result["updated_capsules"] == 2
        assert fixed_pool.capsule_type == "product_pool"
        assert fixed_pool.target_amount == 120000
        assert fixed_pool.monthly_contribution > 0
        assert item_pool.target_amount == 3000
        assert item_pool.monthly_contribution == 3000
    finally:
        db.close()
