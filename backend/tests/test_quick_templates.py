from __future__ import annotations

from app.services.ledger_valuation import calculate_account_valued_balance

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models, schemas
    from backend.app.database import Base
    from backend.app.domain.errors import Invalid
    from backend.app.routers.accounts import delete_account
    from backend.app.routers.quick_templates import create_transaction_batch
except ModuleNotFoundError:
    from app import models, schemas  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.domain.errors import Invalid  # type: ignore[no-redef]
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
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
        receivable = models.Account(client_id=1, name="receivable", account_type="asset")
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
                    currency="JPY",
                    from_account_id=cash.id,
                    to_account_id=food.id,
                ),
                schemas.TransactionCreate(
                    date=date(2026, 5, 8),
                    description="lunch advance",
                    amount=6000,
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
        assert calculate_account_valued_balance(db, cash) == -10000
        assert calculate_account_valued_balance(db, food) == 4000
        assert calculate_account_valued_balance(db, receivable) == 6000
    finally:
        db.close()


def test_account_delete_is_locked_by_active_quick_template() -> None:
    db = _session()
    try:
        client = models.Client(id=1, name="test", general_settings={}, ai_config={})
        cash = models.Account(client_id=1, name="cash", account_type="asset")
        food = models.Account(client_id=1, name="food", account_type="expense")
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

        with pytest.raises(Invalid) as exc:
            delete_account(cash.id, db=db, current_client=client)

        assert str(exc.value) == "Account is used by active quick templates. Delete or update those templates first."
        db.refresh(cash)
        assert cash.is_active is True
    finally:
        db.close()
