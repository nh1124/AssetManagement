from __future__ import annotations

from app.services.money_storage import to_minor


from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.product_reserve_service import (
        product_reserve_values,
    )
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.product_reserve_service import (  # type: ignore[no-redef]
        product_reserve_values,
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_product_reserve_values_for_asset_and_item() -> None:
    client = models.Client(id=1, general_settings={"currency": "JPY"})
    asset = models.Product(
        client=client,
        client_id=1,
        name="Laptop",
        category="Electronics",
        last_unit_price_minor=to_minor(120000, "JPY"),
        is_asset=True,
        purchase_price_minor=to_minor(120000, "JPY"),
        purchase_date=date(2026, 1, 1),
        lifespan_months=24,
    )
    item = models.Product(
        client=client,
        client_id=1,
        name="Coffee beans",
        category="Grocery",
        last_unit_price_minor=to_minor(3000, "JPY"),
        units_per_purchase=1,
        frequency_days=30,
        is_asset=False,
    )
    reserve_item = models.Product(
        client=client,
        client_id=1,
        name="Water filter",
        category="Kitchen",
        last_unit_price_minor=to_minor(6000, "JPY"),
        units_per_purchase=1,
        frequency_days=180,
        is_asset=False,
    )

    assert product_reserve_values(asset, reference_date=date(2026, 1, 1)) == {
        "reserve_target_amount": 120000,
        "recommended_monthly_reserve": 5000,
    }
    assert product_reserve_values(item, reference_date=date(2026, 1, 1)) == {
        "reserve_target_amount": 0.0,
        "recommended_monthly_reserve": 0.0,
    }
    assert product_reserve_values(reserve_item, reference_date=date(2026, 1, 1)) == {
        "reserve_target_amount": 6000,
        "recommended_monthly_reserve": 1000,
    }


