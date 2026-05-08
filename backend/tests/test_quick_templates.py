from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models, schemas
    from backend.app.database import Base
    from backend.app.routers.accounts import delete_account
    from backend.app.routers.quick_templates import create_transaction_batch
except ModuleNotFoundError:
    from app import models, schemas  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers.accounts import delete_account  # type: ignore[no-redef]
    from app.routers.quick_templates import create_transaction_batch  # type: ignore[no-redef]


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return testing_session_local()


def test_transaction_batch_posts_grouped_transactions() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", balance=10_000)
        food = models.Account(client_id=1, name="food", account_type="expense", balance=0)
        receivable = models.Account(client_id=1, name="receivable", account_type="asset", balance=0)
        db.add_all([client, cash, food, receivable])
        db.commit()

        payload = schemas.TransactionBatchCreate(
            label="lunch split",
            input_payload={"tray": "food"},
            transactions=[
                schemas.TransactionCreate(
                    date=date(2026, 5, 8),
                    description="lunch own share",
                    amount=4000,
                    type="Expense",
                    category="food",
                    currency="JPY",
                    from_account_id=cash.id,
                    to_account_id=food.id,
                ),
                schemas.TransactionCreate(
                    date=date(2026, 5, 8),
                    description="lunch advance",
                    amount=6000,
                    type="Transfer",
                    category="advance",
                    currency="JPY",
                    from_account_id=cash.id,
                    to_account_id=receivable.id,
                ),
            ],
        )

        result = create_transaction_batch(payload, db=db, current_client=client)

        assert result["id"] is not None
        assert [tx["batch_id"] for tx in result["transactions"]] == [result["id"], result["id"]]
        db.refresh(cash)
        db.refresh(food)
        db.refresh(receivable)
        assert cash.balance == 0
        assert food.balance == 4000
        assert receivable.balance == 6000
    finally:
        db.close()


def test_account_delete_is_locked_by_active_quick_template() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset", balance=0)
        food = models.Account(client_id=1, name="food", account_type="expense", balance=0)
        db.add_all([client, cash, food])
        db.flush()
        db.add(
            models.QuickTemplate(
                client_id=1,
                tray="food",
                name="lunch",
                template_kind="simple_expense",
                default_from_account_id=cash.id,
                default_to_account_id=food.id,
            )
        )
        db.commit()

        with pytest.raises(HTTPException) as exc:
            delete_account(cash.id, db=db, current_client=client)

        assert exc.value.status_code == 400
        assert "quick templates" in exc.value.detail
        db.refresh(cash)
        assert cash.is_active is True
    finally:
        db.close()
