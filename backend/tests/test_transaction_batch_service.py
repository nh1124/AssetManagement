from app.services.ledger_valuation import calculate_account_valued_balance
from app.services.money_storage import to_minor, rule_amount_fields

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.domain.errors import Conflict, Invalid, NotFound, Refused, status_for
from backend.app.routers import transaction_batches as router
from backend.app.services import ledger_service as ledger
from backend.app.services import transaction_batch_service as service
from backend.app.workflows import transaction_batch_workflow as workflow


@pytest.fixture
def posting():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    client = models.Client(id=1, name="batch-test", general_settings={})
    other = models.Client(id=2, name="other", general_settings={})
    db.add_all([client, other])
    ledger.ensure_default_accounts(db, client_id=1)
    accounts = {row.name: row for row in db.query(models.Account).filter_by(client_id=1)}
    try:
        yield db, client, accounts["cash"], accounts["food"], accounts["savings"]
    finally:
        db.close()
        engine.dispose()


def test_batch_primitive_commit_false_leaves_the_batch_for_the_caller(posting):
    db, client, *_ = posting
    batch_id = service.create_batch(db, client.id, {"label": "pending"}, commit=False).id
    db.rollback()
    assert db.get(models.TransactionBatch, batch_id) is None


def _payload(posting, **overrides):
    _, _, cash, food, reserve = posting
    transactions = [schemas.TransactionCreate(
        date=date(2026, 10, 11), description=f"entry-{i}", amount=100 * i,
        from_account_id=cash.id, to_account_id=food.id, batch_id=999999,
    ) for i in [1, 2]]
    transactions.append(schemas.TransactionCreate(
        date=date(2026, 10, 11), description="entry-3", amount=300, batch_id=999999,
        legs=[schemas.TransactionLeg(account_id=cash.id, credit=300),
              schemas.TransactionLeg(account_id=food.id, debit=250),
              schemas.TransactionLeg(account_id=reserve.id, debit=50)],
    ))
    return schemas.TransactionBatchCreate(**dict(dict(
        label="Lunch batch", source="quick", input_payload={"tray": "food"},
        transactions=transactions,
    ), **overrides))


def _rule(posting, auto_post):
    db, client, cash, _, reserve = posting
    capsule = models.Capsule(client_id=client.id, name="reserve", funding_sources=[models.CapsuleFundingSource(client_id=client.id, account_id=reserve.id, target_amount_minor=to_minor(5000, "JPY") or 0)],
                             target_amount_minor=to_minor(5000, "JPY"), monthly_contribution_minor=to_minor(0, "JPY"), auto_post=auto_post)
    db.add(capsule)
    db.flush()
    db.add(models.CapsuleRule(client_id=client.id, capsule_id=capsule.id, trigger_type="Expense",
                              source_mode="fixed_account", source_account_id=cash.id,
                              amount_type="fixed", **rule_amount_fields(10, "fixed", "JPY"), is_active=True))
    db.commit()


COUNTED = (models.TransactionBatch, models.Transaction, models.JournalEntry, models.TransactionProposal)


def _counts(db):
    return tuple(db.query(model).count() for model in COUNTED)


def _snapshots(db):
    snapshots = []

    def observe(_session):
        with db.get_bind().connect() as connection:
            snapshots.append(tuple(connection.scalar(select(func.count()).select_from(model)) for model in COUNTED))

    event.listen(db, "after_commit", observe)
    return snapshots


@pytest.mark.parametrize("auto_post", [False, True])
def test_batch_posts_every_entry_and_capsule_effect_in_one_commit(posting, auto_post):
    db, client, cash, food, reserve = posting
    _rule(posting, auto_post)
    snapshots = _snapshots(db)
    payload = _payload(posting)
    batch = workflow.post_transaction_batch(db, client.id, payload)
    # Three entries, three reservations. X3 put the trigger in the
    # proposal's idempotency key, so identical reservations from
    # different entries are no longer one row -- which had been
    # reserving a third of what the rule asked for. The auto-posting
    # case keeps its three transfers and now records them too.
    expected = (1, 6, 13, 3) if auto_post else (1, 3, 7, 3)
    assert snapshots == [(0, 0, 0, 0), expected]
    assert _counts(db) == expected
    assert (batch.label, batch.source, batch.input_payload) == ("Lunch batch", "quick", {"tray": "food"})
    assert [tx.description for tx in batch.transactions] == ["entry-1", "entry-2", "entry-3"]
    assert all(tx.batch_id == batch.id for tx in batch.transactions)
    assert sorted((leg.account_id, leg.debit, leg.credit) for leg in batch.transactions[2].journal_entries) == sorted([
        (cash.id, 0, 300), (food.id, 250, 0), (reserve.id, 50, 0),
    ])
    assert (calculate_account_valued_balance(db, cash), calculate_account_valued_balance(db, food), calculate_account_valued_balance(db, reserve)) == ((-630, 550, 80) if auto_post else (-600, 550, 50))
    assert all(tx.batch_id == 999999 for tx in payload.transactions)
    assert service.get_batch(db, client.id, batch.id) is batch
    assert service.list_batches(db, client.id) == [batch]


@pytest.mark.parametrize("auto_post", [False, True])
def test_third_entry_failure_rolls_back_all_entries_legs_capsule_effects_and_batch(posting, monkeypatch, auto_post):
    db, client, cash, food, reserve = posting
    _rule(posting, auto_post)
    snapshots = _snapshots(db)
    original = ledger._post_transaction_journal
    failed = []

    def fail_third(db, transaction, *args, **kwargs):
        if transaction.description == "entry-3":
            failed.append(_counts(db))
            raise ValueError("third entry journal failure")
        return original(db, transaction, *args, **kwargs)

    monkeypatch.setattr(ledger, "_post_transaction_journal", fail_third)
    with pytest.raises(workflow.BatchPostingError, match="third entry journal failure"):
        workflow.post_transaction_batch(db, client.id, _payload(posting))
    # Two entries posted before the third failed, so two reservations.
    assert failed == [(1, 5, 8, 2) if auto_post else (1, 3, 4, 2)]
    assert snapshots == [(0, 0, 0, 0)]
    assert _counts(db) == (0, 0, 0, 0)
    for account in (cash, food, reserve):
        db.refresh(account)
        assert calculate_account_valued_balance(db, account) == 0


def test_batch_reads_are_client_scoped_and_paginated(posting):
    db, client, *_ = posting
    batches = [service.create_batch(db, client.id, {"label": name}) for name in ["first", "second", "third"]]
    other = service.create_batch(db, 2, {"label": "other"})
    assert service.list_batches(db, client.id, limit=1, offset=1) == [batches[1]]
    assert service.get_batch(db, client.id, other.id) is None
    assert service.get_batch(db, client.id, 999999) is None


def test_router_keeps_missing_batch_404(posting):
    db, client, *_ = posting
    with pytest.raises(HTTPException) as exc:
        router.get_transaction_batch(999999, db=db, current_client=client)
    assert (exc.value.status_code, exc.value.detail) == (404, "Transaction batch not found")
    assert _counts(db) == (0, 0, 0, 0)


def test_a_stale_template_id_from_an_old_client_is_ignored(posting):
    db, client, *_ = posting
    payload = schemas.TransactionBatchCreate(**{**_payload(posting).model_dump(), "quick_template_id": 7})
    batch = router.create_transaction_batch(payload, db=db, current_client=client)
    assert "quick_template_id" not in batch
    assert len(batch["transactions"]) == 3


def test_router_keeps_empty_batch_400(posting):
    db, client, *_ = posting
    with pytest.raises(workflow.BatchPostingError) as exc:
        router.create_transaction_batch(_payload(posting, transactions=[]), db=db, current_client=client)
    # test_domain_errors.py pins Invalid to 400 over HTTP.
    assert isinstance(exc.value, Invalid)
    assert str(exc.value) == "At least one transaction is required"
    assert _counts(db) == (0, 0, 0, 0)


def test_batch_unbalanced_legs_remain_400_and_roll_back_all_writes(posting):
    db, client, cash, food, reserve = posting
    _rule(posting, auto_post=False)
    payload = _payload(posting)
    payload.transactions[-1].legs[-1].debit = 40
    with pytest.raises(workflow.BatchPostingError) as error:
        workflow.post_transaction_batch(db, client.id, payload)
    assert status_for(error.value) == 400
    assert str(error.value) == "Journal entry does not balance: debit 290 vs credit 300"
    assert _counts(db) == (0, 0, 0, 0)
    assert all(calculate_account_valued_balance(db, account) == 0 for account in (cash, food, reserve))


@pytest.mark.parametrize("failure", [
    TypeError("Unknown keyword 'unknown_column' for table transactions"),
    RuntimeError("unexpected posting bug"),
    NotFound("missing resource"),
    Invalid("invalid request"),
    Conflict("conflicting request"),
    Refused("request refused"),
    Invalid("explicit status", status_code=422, payload={"reason": "invalid"}),
], ids=["type_error", "runtime_error", "not_found", "invalid", "conflict", "refused", "explicit_status"])
def test_batch_non_value_errors_propagate_unchanged_and_roll_back_all_writes(posting, monkeypatch, failure):
    db, client, cash, food, reserve = posting
    _rule(posting, auto_post=False)
    original = workflow.record_entry

    def fail_second(session, client_id, entry, **kwargs):
        if entry.description == "entry-2":
            assert _counts(session) == (1, 1, 2, 1)
            raise failure
        return original(session, client_id, entry, **kwargs)

    monkeypatch.setattr(workflow, "record_entry", fail_second)
    with pytest.raises(type(failure)) as error:
        workflow.post_transaction_batch(db, client.id, _payload(posting))
    assert error.value is failure
    assert _counts(db) == (0, 0, 0, 0)
    assert all(calculate_account_valued_balance(db, account) == 0 for account in (cash, food, reserve))
