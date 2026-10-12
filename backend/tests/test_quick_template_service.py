from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.domain.errors import Conflict, Invalid, NotFound, Refused, status_for
from backend.app.routers import quick_templates as router
from backend.app.services import ledger_service as ledger
from backend.app.services import quick_template_service as service
from backend.app.workflows import transaction_batch_workflow as workflow


@pytest.fixture
def posting():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    client = models.Client(id=1, name="batch-test", ai_config={}, general_settings={})
    other = models.Client(id=2, name="other", ai_config={}, general_settings={})
    db.add_all([client, other])
    ledger.ensure_default_accounts(db, client_id=1)
    accounts = {row.name: row for row in db.query(models.Account).filter_by(client_id=1)}
    try:
        yield db, client, accounts["cash"], accounts["food"], accounts["savings"]
    finally:
        db.close()
        engine.dispose()


def _template_data(posting, **overrides):
    _, _, cash, food, _ = posting
    return schemas.QuickTemplateCreate(**dict(
        dict(tray="food", name="Lunch", template_kind="simple_expense",
             default_from_account_id=cash.id, default_to_account_id=food.id,
             config={"amount": 100}), **overrides,
    )).model_dump()


def test_template_crud_returns_rows_and_soft_deletes(posting):
    db, client, cash, food, _ = posting
    template = service.create_template(db, client.id, _template_data(posting))
    assert service._get_template(db, client.id, template.id) is template
    assert service.list_templates(db, client.id) == [template]
    assert (template.default_from_account_id, template.default_to_account_id) == (cash.id, food.id)
    changed = service.update_template(db, client.id, template.id, {
        "name": "Dinner", "default_to_account_id": None, "config": {"amount": 200},
    })
    assert changed is template
    assert (template.name, template.default_to_account_id, template.config) == ("Dinner", None, {"amount": 200})
    assert service.delete_template(db, client.id, template.id) is True
    assert service.list_templates(db, client.id) == []
    assert service.list_templates(db, client.id, include_inactive=True) == [template]
    assert service._get_template(db, client.id, template.id) is template
    assert template.is_active is False


@pytest.mark.parametrize("missing", ["unknown_id", "other_client"])
def test_template_not_found_returns_none_for_lookup_update_and_delete(posting, missing):
    db, client, *_ = posting
    template = service.create_template(db, 2, _template_data(posting,
                                       default_from_account_id=None, default_to_account_id=None))
    template_id = 999999 if missing == "unknown_id" else template.id
    assert service._get_template(db, client.id, template_id) is None
    assert service.update_template(db, client.id, template_id, {"name": "changed"}) is None
    assert service.delete_template(db, client.id, template_id) is None
    assert service.create_batch(db, client.id, {"quick_template_id": template_id}) is None
    assert template.name == "Lunch"
    assert template.is_active is True
    assert db.query(models.TransactionBatch).count() == 0


def test_template_list_preserves_client_tray_activity_and_order(posting):
    db, client, *_ = posting
    data = [dict(name="Z", sort_order=1), dict(name="B"), dict(name="A"),
            dict(tray="travel"), dict(name="inactive", is_active=False)]
    templates = [service.create_template(db, client.id, _template_data(posting, **values)) for values in data]
    service.create_template(db, 2, _template_data(posting,
                            default_from_account_id=None, default_to_account_id=None))
    assert service.list_templates(db, client.id) == [templates[i] for i in [2, 1, 0, 3]]
    assert service.list_templates(db, client.id, tray="food") == [templates[i] for i in [2, 1, 0]]
    assert service.list_templates(db, client.id, tray="food", include_inactive=True) == [
        templates[i] for i in [2, 1, 4, 0]
    ]


@pytest.mark.parametrize("field", ["default_from", "default_to"])
@pytest.mark.parametrize("missing", ["unknown_id", "other_client", "inactive"])
def test_account_reference_preserves_each_not_found_error(posting, field, missing):
    db, client, cash, *_ = posting
    account_id = 999999
    if missing == "other_client":
        account = ledger.create_account(db, 2, {"name": "foreign", "account_type": "asset"})
        account_id = account.id
    elif missing == "inactive":
        cash.is_active = False
        db.commit()
        account_id = cash.id
    with pytest.raises(Invalid) as exc:
        service._validate_account_reference(db, client.id, account_id, field)
    assert str(exc.value) == f"{field} account not found"


def test_account_reference_accepts_none_and_an_active_owned_account(posting):
    db, client, cash, *_ = posting
    service._validate_account_reference(db, client.id, None, "default_from")
    service._validate_account_reference(db, client.id, cash.id, "default_from")


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("field", ["default_from_account_id", "default_to_account_id"])
def test_template_writes_validate_both_account_references(posting, operation, field):
    db, client, *_ = posting
    other = ledger.create_account(db, 2, {"name": "foreign", "account_type": "asset"})
    template = service.create_template(db, client.id, _template_data(posting))
    before = (template.default_from_account_id, template.default_to_account_id)
    with pytest.raises(Invalid) as exc:
        if operation == "create":
            service.create_template(db, client.id, _template_data(posting, **{field: other.id}))
        else:
            service.update_template(db, client.id, template.id, {field: other.id})
    assert str(exc.value) == f"{field.removesuffix('_account_id')} account not found"
    assert db.query(models.QuickTemplate).count() == 1
    assert (template.default_from_account_id, template.default_to_account_id) == before


def test_template_and_batch_primitives_commit_false_leave_changes_for_the_caller(posting):
    db, client, *_ = posting
    template = service.create_template(db, client.id, _template_data(posting))
    pending = service.create_template(db, client.id, _template_data(posting, name="pending"), commit=False)
    service.update_template(db, client.id, template.id, {"name": "changed"}, commit=False)
    service.delete_template(db, client.id, template.id, commit=False)
    batch = service.create_batch(db, client.id, {"quick_template_id": template.id}, commit=False)
    pending_id, batch_id = pending.id, batch.id
    db.rollback()
    assert db.get(models.QuickTemplate, pending_id) is None
    assert db.get(models.TransactionBatch, batch_id) is None
    assert (template.name, template.is_active) == ("Lunch", True)


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
    capsule = models.Capsule(client_id=client.id, name="reserve", account_id=reserve.id,
                             target_amount=5000, monthly_contribution=0, auto_post=auto_post)
    db.add(capsule)
    db.flush()
    db.add(models.CapsuleRule(client_id=client.id, capsule_id=capsule.id, trigger_type="Expense",
                              source_mode="fixed_account", source_account_id=cash.id,
                              amount_type="fixed", amount_value=10, is_active=True))
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
    template = service.create_template(db, client.id, _template_data(posting))
    _rule(posting, auto_post)
    snapshots = _snapshots(db)
    payload = _payload(posting, quick_template_id=template.id)
    batch = workflow.post_transaction_batch(db, client.id, payload)
    expected = (1, 6, 13, 0) if auto_post else (1, 3, 7, 1)
    assert snapshots == [(0, 0, 0, 0), expected]
    assert _counts(db) == expected
    assert (batch.quick_template_id, batch.label, batch.source, batch.input_payload) == (
        template.id, "Lunch batch", "quick", {"tray": "food"},
    )
    assert [tx.description for tx in batch.transactions] == ["entry-1", "entry-2", "entry-3"]
    assert all(tx.batch_id == batch.id for tx in batch.transactions)
    assert sorted((leg.account_id, leg.debit, leg.credit) for leg in batch.transactions[2].journal_entries) == sorted([
        (cash.id, 0, 300), (food.id, 250, 0), (reserve.id, 50, 0),
    ])
    assert (cash.balance, food.balance, reserve.balance) == ((-630, 550, 80) if auto_post else (-600, 550, 50))
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
    assert failed == [(1, 5, 8, 0) if auto_post else (1, 3, 4, 1)]
    assert snapshots == [(0, 0, 0, 0)]
    assert _counts(db) == (0, 0, 0, 0)
    for account in (cash, food, reserve):
        db.refresh(account)
        assert account.balance == 0


def test_batch_reads_are_client_scoped_and_paginated(posting):
    db, client, *_ = posting
    batches = [service.create_batch(db, client.id, {"label": name}) for name in ["first", "second", "third"]]
    other = service.create_batch(db, 2, {"label": "other"})
    assert service.list_batches(db, client.id, limit=1, offset=1) == [batches[1]]
    assert service.get_batch(db, client.id, other.id) is None
    assert service.get_batch(db, client.id, 999999) is None


@pytest.mark.parametrize("operation,detail", [
    ("update_template", "Quick template not found"),
    ("delete_template", "Quick template not found"),
    ("get_batch", "Transaction batch not found"),
    ("post_batch", "Quick template not found"),
])
def test_router_keeps_missing_resource_404s(posting, operation, detail):
    db, client, *_ = posting
    with pytest.raises(HTTPException) as exc:
        if operation == "update_template":
            router.update_quick_template(999999, schemas.QuickTemplateUpdate(name="missing"), db=db, current_client=client)
        elif operation == "delete_template":
            router.delete_quick_template(999999, db=db, current_client=client)
        elif operation == "get_batch":
            router.get_transaction_batch(999999, db=db, current_client=client)
        else:
            router.create_transaction_batch(_payload(posting, quick_template_id=999999), db=db, current_client=client)
    assert (exc.value.status_code, exc.value.detail) == (404, detail)
    assert _counts(db) == (0, 0, 0, 0)


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
    assert db.query(models.CapsuleHolding).count() == 0
    assert all(account.balance == 0 for account in (cash, food, reserve))


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
    assert db.query(models.CapsuleHolding).count() == 0
    assert all(account.balance == 0 for account in (cash, food, reserve))
