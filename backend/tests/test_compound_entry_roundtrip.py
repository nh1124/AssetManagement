"""Exporting and re-importing a compound entry (P7-001 Wave 3c).

The export carries the legs and no longer carries the from/to pair, since the
columns are gone. A payload from before that still has the pair, and importing
one has to ignore it and rebuild the accounts from the legs -- which is where
they came from.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models, schemas
    from backend.app.database import Base
    from backend.app.routers import transactions as transaction_router
    from backend.app.routers.data_transfer import (
        EXPORT_VERSION,
        ImportPayload,
        export_client_data,
        import_client_data,
        validate_import_client_data,
    )
    from backend.app.utils.password import hash_password
except ModuleNotFoundError:  # pragma: no cover - import shim used by the container
    from app import models, schemas  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.routers import transactions as transaction_router  # type: ignore[no-redef]
    from app.routers.data_transfer import (  # type: ignore[no-redef]
        EXPORT_VERSION,
        ImportPayload,
        export_client_data,
        import_client_data,
        validate_import_client_data,
    )
    from app.utils.password import hash_password  # type: ignore[no-redef]

WHEN = date(2026, 10, 5)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db) -> models.Client:
    client = models.Client(
        id=1,
        name="Test",
        username="roundtrip-test",
        password_hash=hash_password("password123"),
        ai_config={},
        general_settings={},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def _split_entry(db, client):
    card = models.Account(
        client_id=client.id, name="card", account_type="liability", liability_kind="card", balance=0
    )
    food = models.Account(client_id=client.id, name="food", account_type="expense", balance=0)
    advance = models.Account(client_id=client.id, name="advance", account_type="asset", balance=0)
    db.add_all([card, food, advance])
    db.commit()

    created = transaction_router.create_transaction(
        transaction=schemas.TransactionCreate(
            date=WHEN,
            description="dinner with a friend",
            amount=5000,
            currency="JPY",
            legs=[
                schemas.TransactionLeg(account_id=card.id, credit=5000),
                schemas.TransactionLeg(account_id=food.id, debit=3000, memo="own share"),
                schemas.TransactionLeg(account_id=advance.id, debit=2000, memo="advance"),
            ],
        ),
        db=db,
        current_client=client,
    )
    return created, card, food, advance


def test_the_export_carries_the_legs_and_not_the_pair() -> None:
    db = _session()
    try:
        client = _client(db)
        _split_entry(db, client)

        snapshot = export_client_data(db=db, current_client=client)

        assert snapshot["version"] == EXPORT_VERSION
        row = snapshot["data"]["transactions"][0]
        assert "from_account_id" not in row
        assert "to_account_id" not in row
        legs = [
            entry
            for entry in snapshot["data"]["journal_entries"]
            if entry["transaction_id"] == row["id"]
        ]
        assert len(legs) == 3
        assert sum(leg["debit"] or 0 for leg in legs) == 5000
        assert sum(leg["credit"] or 0 for leg in legs) == 5000
        assert {leg["memo"] for leg in legs} == {None, "own share", "advance"}

        validation = validate_import_client_data(
            payload=ImportPayload(**snapshot), current_client=client
        )
        assert validation["status"] == "valid"
    finally:
        db.close()


def test_importing_the_export_rebuilds_the_three_legs() -> None:
    db = _session()
    try:
        client = _client(db)
        _split_entry(db, client)
        snapshot = export_client_data(db=db, current_client=client)

        import_client_data(payload=ImportPayload(**snapshot), db=db, current_client=client)

        transactions = db.query(models.Transaction).filter_by(client_id=client.id).all()
        assert len(transactions) == 1
        entries = (
            db.query(models.JournalEntry)
            .filter(models.JournalEntry.transaction_id == transactions[0].id)
            .all()
        )
        assert len(entries) == 3
        assert sum(entry.debit or 0.0 for entry in entries) == 5000
        assert sum(entry.credit or 0.0 for entry in entries) == 5000

        # The pair is derived on the way out: three legs means two debits, so
        # there is no single destination to name.
        listed = transaction_router.get_transactions(
            db=db, current_client=client,
            start_date=None, end_date=None, amount_min=None, amount_max=None,
            account_id=None, q=None, limit=50, offset=0, paginated=False,
        )
        serialized = listed[0]
        assert serialized["from_account_id"] is not None
        assert serialized["to_account_id"] is None
        assert len(serialized["legs"]) == 3
    finally:
        db.close()


def test_an_older_payload_with_the_pair_still_imports() -> None:
    db = _session()
    try:
        client = _client(db)
        _split_entry(db, client)
        snapshot = export_client_data(db=db, current_client=client)

        # What a version 6 export looked like: the header named two accounts,
        # which for this entry could only ever have been half a truth.
        legacy = dict(snapshot)
        legacy["version"] = 6
        row = dict(legacy["data"]["transactions"][0])
        accounts = {account["name"]: account["id"] for account in legacy["data"]["accounts"]}
        row["from_account_id"] = accounts["card"]
        row["to_account_id"] = accounts["food"]
        legacy["data"] = {**legacy["data"], "transactions": [row]}

        validation = validate_import_client_data(
            payload=ImportPayload(**legacy), current_client=client
        )
        assert validation["status"] == "valid"
        assert any(issue["code"] == "older_version" for issue in validation["issues"])

        import_client_data(payload=ImportPayload(**legacy), db=db, current_client=client)

        transactions = db.query(models.Transaction).filter_by(client_id=client.id).all()
        assert len(transactions) == 1
        entries = (
            db.query(models.JournalEntry)
            .filter(models.JournalEntry.transaction_id == transactions[0].id)
            .all()
        )
        # The legs, not the pair, decided what was imported.
        assert len(entries) == 3
        assert sum(entry.debit or 0.0 for entry in entries) == 5000
    finally:
        db.close()
