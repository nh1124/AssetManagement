"""Posting, editing and listing a compound entry through the API (P7-001 Wave 2).

The invariant: two or more legs, each on exactly one side, both sides equal and
equal to the transaction amount. The amount is a denormalisation of the legs,
so it serves as the checksum.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.routers import quick_templates as quick_template_router
from backend.app.routers import transactions as transaction_router
from backend.app.services.data_health_service import check_data_health
from backend.app.utils.password import hash_password

WHEN = date(2026, 10, 5)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _client(db) -> models.Client:
    client = models.Client(
        id=1, name="Test", username="legs-test",
        password_hash=hash_password("password123"), ai_config={}, general_settings={},
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def _accounts(db):
    card = models.Account(
        client_id=1, name="card", account_type="liability", liability_kind="card", balance=0
    )
    food = models.Account(client_id=1, name="food", account_type="expense", balance=0)
    advance = models.Account(client_id=1, name="advance", account_type="asset", balance=0)
    db.add_all([card, food, advance])
    db.commit()
    return card, food, advance


def _list_transactions(db, client, **overrides):
    """Call the list endpoint directly.

    Every parameter has to be passed: outside a request, the Query(...)
    defaults are Query objects, and a Query object is truthy.
    """
    params = {
        "start_date": None, "end_date": None, "type": None, "category": None,
        "amount_min": None, "amount_max": None, "account_id": None, "q": None,
        "limit": 50, "offset": 0, "paginated": False,
    }
    params.update(overrides)
    return transaction_router.get_transactions(db=db, current_client=client, **params)


def _split_payload(card, food, advance, amount=5000):
    return schemas.TransactionCreate(
        date=WHEN,
        description="dinner with a friend",
        amount=amount,
        type="CreditExpense",
        currency="JPY",
        legs=[
            schemas.TransactionLeg(account_id=card.id, credit=amount),
            schemas.TransactionLeg(account_id=food.id, debit=3000, memo="own share"),
            schemas.TransactionLeg(account_id=advance.id, debit=amount - 3000, memo="advance"),
        ],
    )


def test_posting_three_legs_writes_three_entries_and_moves_each_balance() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)

        result = transaction_router.create_transaction(
            _split_payload(card, food, advance), db=db, current_client=client
        )

        # Legs keep the order they were given; sort_order is the input index.
        assert [(leg["account_id"], leg["debit"], leg["credit"]) for leg in result["legs"]] == [
            (card.id, 0.0, 5000.0),
            (food.id, 3000.0, 0.0),
            (advance.id, 2000.0, 0.0),
        ]
        db.refresh(card), db.refresh(food), db.refresh(advance)
        assert card.balance == 5000       # a liability grows on the credit side
        assert food.balance == 3000
        assert advance.balance == 2000
    finally:
        db.close()


def test_the_denormalised_columns_name_only_a_single_leg_a_side() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)

        result = transaction_router.create_transaction(
            _split_payload(card, food, advance), db=db, current_client=client
        )

        # One credit leg, so from_account_id still means something; three debit
        # legs would make to_account_id a lie, so it is left empty.
        assert result["from_account_id"] == card.id
        assert result["to_account_id"] is None
    finally:
        db.close()


@pytest.mark.parametrize(
    "legs_kwargs, message",
    [
        ([("card", 0, 5000)], "at least two legs"),
        ([("card", 0, 5000), ("food", 2000, 0)], "does not balance"),
        ([("card", 0, 5000), ("food", 3000, 0), ("advance", 1000, 0)], "does not balance"),
        # Both sides equal, but they do not come to the stated amount.
        ([("card", 0, 4000), ("food", 4000, 0)], "does not match the transaction amount"),
        ([("card", 100, 5000), ("food", 5000, 0)], "either a debit or a credit"),
        ([("card", 0, 0), ("food", 0, 0)], "either a debit or a credit"),
    ],
)
def test_an_entry_that_breaks_the_invariant_is_refused(legs_kwargs, message) -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)
        by_name = {"card": card, "food": food, "advance": advance}
        payload = schemas.TransactionCreate(
            date=WHEN, description="bad entry", amount=5000, type="CreditExpense", currency="JPY",
            legs=[
                schemas.TransactionLeg(account_id=by_name[name].id, debit=debit, credit=credit)
                for name, debit, credit in legs_kwargs
            ],
        )

        with pytest.raises(ValueError, match=message):
            transaction_router.create_transaction(payload, db=db, current_client=client)

        assert db.query(models.Transaction).count() == 0
        assert db.query(models.JournalEntry).count() == 0
    finally:
        db.close()


def test_an_account_from_another_client_is_refused() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, _advance = _accounts(db)
        other = models.Account(client_id=2, name="their account", account_type="expense", balance=0)
        db.add(other)
        db.commit()
        payload = schemas.TransactionCreate(
            date=WHEN, description="leak", amount=1000, type="Expense", currency="JPY",
            legs=[
                schemas.TransactionLeg(account_id=card.id, credit=1000),
                schemas.TransactionLeg(account_id=other.id, debit=1000),
            ],
        )

        with pytest.raises(ValueError, match="not found for this client"):
            transaction_router.create_transaction(payload, db=db, current_client=client)
        assert db.query(models.Transaction).count() == 0
    finally:
        db.close()


def test_a_two_leg_transaction_still_posts_without_legs() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, _advance = _accounts(db)

        result = transaction_router.create_transaction(
            schemas.TransactionCreate(
                date=WHEN, description="coffee", amount=500, type="CreditExpense",
                currency="JPY", from_account_id=card.id, to_account_id=food.id,
            ),
            db=db, current_client=client,
        )

        assert len(result["legs"]) == 2
        assert result["from_account_id"] == card.id
        assert result["to_account_id"] == food.id
    finally:
        db.close()


def test_editing_the_legs_rebuilds_them_and_the_balances() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)
        created = transaction_router.create_transaction(
            _split_payload(card, food, advance), db=db, current_client=client
        )

        # The friend owed 1,500, not 2,000.
        updated = transaction_router.update_transaction(
            created["id"],
            schemas.TransactionUpdate(legs=[
                schemas.TransactionLeg(account_id=card.id, credit=5000),
                schemas.TransactionLeg(account_id=food.id, debit=3500),
                schemas.TransactionLeg(account_id=advance.id, debit=1500),
            ]),
            db=db, current_client=client,
        )

        assert sorted((leg["account_id"], leg["debit"]) for leg in updated["legs"]) == sorted(
            [(card.id, 0.0), (food.id, 3500.0), (advance.id, 1500.0)]
        )
        db.refresh(card), db.refresh(food), db.refresh(advance)
        assert (card.balance, food.balance, advance.balance) == (5000, 3500, 1500)
        assert db.query(models.JournalEntry).count() == 3
    finally:
        db.close()


def test_deleting_a_compound_entry_puts_every_balance_back() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)
        created = transaction_router.create_transaction(
            _split_payload(card, food, advance), db=db, current_client=client
        )

        transaction_router.delete_transaction(created["id"], db=db, current_client=client)

        db.refresh(card), db.refresh(food), db.refresh(advance)
        assert (card.balance, food.balance, advance.balance) == (0, 0, 0)
        assert db.query(models.JournalEntry).count() == 0
    finally:
        db.close()


def test_filtering_by_account_reports_that_account_s_leg_not_the_total() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)
        transaction_router.create_transaction(
            _split_payload(card, food, advance), db=db, current_client=client
        )

        # The expense account only ever saw 3,000 of the 5,000 bill.
        on_food = _list_transactions(db, client, account_id=food.id)
        assert len(on_food) == 1
        assert on_food[0]["amount"] == 5000
        assert on_food[0]["matched_debit"] == 3000

        on_card = _list_transactions(db, client, account_id=card.id)
        assert on_card[0]["matched_credit"] == 5000

        # And the receivable is reachable at all, which from/to could not express.
        on_advance = _list_transactions(db, client, account_id=advance.id)
        assert len(on_advance) == 1
        assert on_advance[0]["matched_debit"] == 2000
    finally:
        db.close()


def test_data_health_reports_an_entry_whose_legs_do_not_balance() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, _advance = _accounts(db)
        tx = models.Transaction(
            client_id=1, date=WHEN, description="hand-edited", amount=5000,
            type="CreditExpense", currency="JPY",
        )
        db.add(tx)
        db.flush()
        db.add_all([
            models.JournalEntry(transaction_id=tx.id, account_id=card.id, debit=0, credit=5000),
            models.JournalEntry(transaction_id=tx.id, account_id=food.id, debit=4000, credit=0),
        ])
        db.commit()

        report = check_data_health(db, client.id)
        issue = next(i for i in report["issues"] if i["code"] == "journal_unbalanced")

        assert issue["count"] == 1
        assert issue["items"][0]["transaction_id"] == tx.id
        assert issue["items"][0]["problem"] == "sides_disagree"
        assert issue["repairable"] is False
    finally:
        db.close()


def test_data_health_is_quiet_when_every_entry_balances() -> None:
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)
        transaction_router.create_transaction(
            _split_payload(card, food, advance), db=db, current_client=client
        )

        report = check_data_health(db, client.id)
        issue = next(i for i in report["issues"] if i["code"] == "journal_unbalanced")

        assert issue["count"] == 0
    finally:
        db.close()


def test_a_batch_can_carry_a_compound_entry() -> None:
    """The quick template posts through /transaction-batches/, not /transactions/.

    "Expense with advance" used to expand into two or three transactions for one
    payment. It is now one compound entry, plus a separate transaction only if
    the money has already come back.
    """
    db = _session()
    try:
        client = _client(db)
        card, food, advance = _accounts(db)
        cash = models.Account(client_id=1, name="cash", account_type="asset", role="operating", balance=0)
        db.add(cash)
        db.commit()

        batch = quick_template_router.create_transaction_batch(
            schemas.TransactionBatchCreate(
                label="dinner with a friend",
                source="quick",
                input_payload={"template_kind": "expense_with_advance"},
                transactions=[
                    schemas.TransactionCreate(
                        date=WHEN, description="dinner with a friend", amount=5000,
                        type="CreditExpense", currency="JPY", from_account_id=card.id,
                        legs=[
                            schemas.TransactionLeg(account_id=card.id, credit=5000),
                            schemas.TransactionLeg(account_id=food.id, debit=3000, memo="own share"),
                            schemas.TransactionLeg(account_id=advance.id, debit=2000, memo="advance"),
                        ],
                    ),
                    # The friend paid their share back the same day.
                    schemas.TransactionCreate(
                        date=WHEN, description="dinner with a friend 精算", amount=2000,
                        type="Transfer", currency="JPY",
                        from_account_id=advance.id, to_account_id=cash.id,
                    ),
                ],
            ),
            db=db, current_client=client,
        )

        assert len(batch["transactions"]) == 2
        entries = db.query(models.JournalEntry).count()
        assert entries == 5          # three legs plus the settlement's two
        db.refresh(advance)
        assert advance.balance == 0  # fronted 2,000 and got it back
        db.refresh(food)
        assert food.balance == 3000
    finally:
        db.close()
