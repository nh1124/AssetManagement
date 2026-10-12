from app.services.ledger_valuation import calculate_account_valued_balance
from app.services.money_storage import to_minor, rule_amount_fields

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.routers import transactions as router
from backend.app.services import ledger_service as ledger
from backend.app.workflows import ledger_entry_workflow as workflow

WHEN = date(2026, 10, 11)


@pytest.fixture
def posting():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    client = models.Client(id=1, name="workflow-test", ai_config={}, general_settings={})
    db.add(client)
    ledger.ensure_default_accounts(db, client_id=1)
    cash = db.query(models.Account).filter_by(client_id=1, name="cash").one()
    food = db.query(models.Account).filter_by(client_id=1, name="food").one()
    reserve = db.query(models.Account).filter_by(client_id=1, name="savings").one()
    try:
        yield db, client, cash, food, reserve
    finally:
        db.close()
        engine.dispose()


def _payload(posting, **overrides):
    _, _, cash, food, _ = posting
    data = dict(
        date=WHEN, description="Lunch", amount=1000, currency="JPY",
        from_account_id=cash.id, to_account_id=food.id,
    )
    data.update(overrides)
    return schemas.TransactionCreate(**data)


def _rule(posting, *, auto_post=False):
    db, client, cash, _, reserve = posting
    capsule = models.Capsule(
        client_id=client.id, name="Savings", funding_sources=[models.CapsuleFundingSource(client_id=client.id, account_id=reserve.id, target_amount_minor=to_minor(5000, "JPY") or 0)],
        target_amount_minor=to_minor(5000, "JPY"), monthly_contribution_minor=to_minor(0, "JPY"), auto_post=auto_post,
    )
    db.add(capsule)
    db.flush()
    rule = models.CapsuleRule(
        client_id=client.id, capsule_id=capsule.id, trigger_type="Expense",
        source_mode="fixed_account", source_account_id=cash.id,
        amount_type="fixed", **rule_amount_fields(100, "fixed", "JPY"), is_active=True,
    )
    db.add(rule)
    db.commit()
    return capsule, rule


def _counts(db):
    return tuple(db.query(model).count() for model in (
        models.Transaction, models.JournalEntry, models.TransactionProposal,
    ))


def _committed_counts(db):
    snapshots = []
    engine = db.get_bind()

    def observe(_session):
        with engine.connect() as connection:
            snapshots.append(tuple(connection.scalar(
                select(func.count()).select_from(model)
            ) for model in (
                models.Transaction, models.JournalEntry, models.TransactionProposal,
            )))

    event.listen(db, "after_commit", observe)
    return snapshots


@pytest.mark.parametrize("auto_post", [False, True])
def test_record_entry_commits_posting_legs_and_capsule_reservation_together(posting, auto_post):
    db, client, cash, food, reserve = posting
    capsule, rule = _rule(posting, auto_post=auto_post)
    snapshots = _committed_counts(db)

    tx = workflow.record_entry(db, client.id, _payload(posting))

    # X3: an auto-posted reservation records a proposal as well as the
    # transfer, because the proposal is what says which entry caused it.
    expected = (2, 4, 1) if auto_post else (1, 2, 1)
    # Default-account bootstrap still commits first; no commit may expose only
    # part of the posting and the reservation that it triggered.
    assert snapshots == [(0, 0, 0), expected]
    assert _counts(db) == expected
    assert sorted((leg.account_id, leg.debit, leg.credit) for leg in tx.journal_entries) == sorted([
        (cash.id, 0, 1000), (food.id, 1000, 0),
    ])
    if not auto_post:
        proposal = db.query(models.TransactionProposal).one()
        assert proposal.origin == "capsule"
        assert proposal.origin_ref == {"capsule_id": capsule.id, "rule_id": rule.id}
        assert proposal.trigger_transaction_id == tx.id
        assert sorted((leg["account_id"], leg["debit"], leg["credit"]) for leg in proposal.legs) == sorted([
            (cash.id, 0, 100), (reserve.id, 100, 0),
        ])


def test_record_entry_rolls_back_posting_legs_and_proposals_when_capsule_posting_raises(posting, monkeypatch):
    db, client, cash, food, reserve = posting
    _rule(posting)
    _rule(posting, auto_post=True)
    snapshots = _committed_counts(db)
    original = ledger._post_transaction_journal
    calls = 0

    def fail_on_capsule_posting(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            # Two proposals: the queued rule's, and the auto-posting
            # rule's, whose legs are the ones about to fail.
            assert _counts(db) == (2, 2, 2)
            raise ValueError("forced journal failure")
        return original(*args, **kwargs)

    # Same seam as test_journal_atomicity: the reservation row has reached the
    # session before its legs fail, after an earlier rule queued a proposal.
    monkeypatch.setattr(ledger, "_post_transaction_journal", fail_on_capsule_posting)
    with pytest.raises(ValueError, match="forced journal failure"):
        workflow.record_entry(db, client.id, _payload(posting))

    assert calls == 2
    assert snapshots == [(0, 0, 0)]
    assert _counts(db) == (0, 0, 0)
    for account in (cash, food, reserve):
        db.refresh(account)
        assert calculate_account_valued_balance(db, account) == 0


def test_record_entry_explicit_legs_and_from_to_shorthand_produce_the_same_legs(posting):
    db, client, cash, food, _ = posting
    shorthand = workflow.record_entry(db, client.id, _payload(posting))
    explicit = workflow.record_entry(db, client.id, _payload(
        posting, from_account_id=None, to_account_id=None,
        legs=[
            schemas.TransactionLeg(account_id=food.id, debit=1000),
            schemas.TransactionLeg(account_id=cash.id, credit=1000),
        ],
    ))
    expected = [(food.id, 1000, 0, None, 0), (cash.id, 0, 1000, None, 1)]
    for tx in (shorthand, explicit):
        assert [(leg.account_id, leg.debit, leg.credit, leg.memo, leg.sort_order)
                for leg in sorted(tx.journal_entries, key=lambda leg: leg.sort_order)] == expected


@pytest.mark.parametrize("operation", ["amend", "remove"])
@pytest.mark.parametrize("commit", [True, False])
def test_amend_and_remove_unknown_id_return_missing_and_write_nothing(posting, operation, commit):
    db, client, *_ = posting
    writes = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", observe)
    if operation == "amend":
        result = workflow.amend_entry(
            db, client.id, 999999, schemas.TransactionUpdate(amount=2000), commit=commit,
        )
        assert result is None
    else:
        assert workflow.remove_entry(db, client.id, 999999, commit=commit) is False
    assert writes == []
    assert _counts(db) == (0, 0, 0)


@pytest.fixture
def entries(posting):
    db, client, cash, _, reserve = posting
    rows = [workflow.record_entry(db, client.id, _payload(posting, **data)) for data in [
        dict(date=date(2026, 10, 9), description="Breakfast", amount=100),
        dict(date=date(2026, 10, 10), description="Lunch", amount=200),
        dict(description="Dinner", amount=300),
        dict(description="Split LUNCH", amount=400, from_account_id=None, to_account_id=None,
             legs=[dict(account_id=cash.id, credit=400),
                   dict(account_id=posting[3].id, debit=250),
                   dict(account_id=reserve.id, debit=150)]),
    ]]
    other = models.Client(id=2, name="other-client", ai_config={}, general_settings={})
    db.add(other)
    ledger.ensure_default_accounts(db, client_id=2)
    other_accounts = db.query(models.Account).filter_by(client_id=2).all()
    workflow.record_entry(db, other.id, schemas.TransactionCreate(
        date=WHEN, description="Other Lunch", amount=200,
        from_account_id=other_accounts[0].id, to_account_id=other_accounts[1].id,
    ))
    return rows


@pytest.mark.parametrize("filters, indices", [
    ({}, [3, 2, 1, 0]),
    ({"start_date": date(2026, 10, 10)}, [3, 2, 1]),
    ({"end_date": date(2026, 10, 10)}, [1, 0]),
    ({"amount_min": 200}, [3, 2, 1]),
    ({"amount_min": 0}, [3, 2, 1, 0]),
    ({"amount_max": 200}, [1, 0]),
    ({"amount_max": 0}, []),
    ({"q": "lUnCh"}, [3, 1]),
    ({"start_date": date(2026, 10, 10), "amount_max": 200, "q": "lunch"}, [1]),
    ({"limit": 2, "offset": 1}, [2, 1]),
])
def test_list_entries_honours_filters_and_total_changes_only_the_second_element(posting, entries, filters, indices):
    db, client, *_ = posting
    rows, total = workflow.list_entries(db, client.id, **filters, with_total=False)
    counted_rows, counted_total = workflow.list_entries(db, client.id, **filters, with_total=True)
    assert rows == counted_rows == [entries[index] for index in indices]
    assert total is None
    assert counted_total == (4 if "limit" in filters else len(indices))


def test_list_entries_account_filter_matches_compound_legs_and_eager_loads_accounts(posting, entries):
    db, client, cash, food, reserve = posting
    rows, total = workflow.list_entries(db, client.id, account_id=reserve.id, with_total=True)
    assert rows == [entries[3]]
    assert total == 1
    rows_without_total, no_total = workflow.list_entries(db, client.id, account_id=reserve.id)
    assert rows_without_total == rows
    assert no_total is None
    db.expunge_all()
    assert sorted((leg.account.name, leg.debit, leg.credit) for leg in rows[0].journal_entries) == sorted([
        (cash.name, 0, 400), (food.name, 250, 0), (reserve.name, 150, 0),
    ])


def test_record_entry_commit_false_leaves_posting_and_reservation_for_the_caller(posting):
    db, client, *_ = posting
    _rule(posting)
    snapshots = _committed_counts(db)
    workflow.record_entry(db, client.id, _payload(posting), commit=False)
    db.flush()
    assert snapshots == []
    assert _counts(db) == (1, 2, 1)
    db.rollback()
    assert _counts(db) == (0, 0, 0)


@pytest.mark.parametrize("operation", ["amend", "remove"])
def test_amend_and_remove_commit_false_leave_reversal_and_posting_for_the_caller(posting, operation):
    db, client, cash, food, _ = posting
    tx = workflow.record_entry(db, client.id, _payload(posting))
    transaction_id = tx.id
    snapshots = _committed_counts(db)
    if operation == "amend":
        result = workflow.amend_entry(
            db, client.id, transaction_id, schemas.TransactionUpdate(amount=2000), commit=False,
        )
        assert result.amount == 2000
        db.flush()
        assert (calculate_account_valued_balance(db, cash), calculate_account_valued_balance(db, food)) == (-2000, 2000)
    else:
        assert workflow.remove_entry(db, client.id, transaction_id, commit=False) is True
        assert (calculate_account_valued_balance(db, cash), calculate_account_valued_balance(db, food)) == (0, 0)
    db.flush()
    assert snapshots == []
    db.rollback()
    assert db.query(models.Transaction).one().amount == 1000
    assert _counts(db) == (1, 2, 0)
    assert (calculate_account_valued_balance(db, cash), calculate_account_valued_balance(db, food)) == (-1000, 1000)


def test_router_list_preserves_plain_and_paginated_response_shapes(posting, entries):
    db, client, *_ = posting
    params = dict(
        start_date=None, end_date=None, amount_min=None, amount_max=None,
        account_id=None, q=None, limit=2, offset=1,
        db=db, current_client=client,
    )
    plain = router.get_transactions(**params, paginated=False)
    paginated = router.get_transactions(**params, paginated=True)
    assert isinstance(plain, list)
    assert paginated == {"items": plain, "total": 4}
    assert [row["id"] for row in plain] == [entries[2].id, entries[1].id]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_proposal_handlers_preserve_decisions_and_refuse_a_second_decision(posting, decision):
    db, client, *_ = posting
    _rule(posting)
    workflow.record_entry(db, client.id, _payload(posting))
    proposal = db.query(models.TransactionProposal).one()
    proposal_id = proposal.id

    def decide():
        if decision == "approve":
            return router.approve_proposal(proposal_id, db=db, current_client=client)
        return router.reject_proposal(
            proposal_id, schemas.TransactionProposalDecision(note="Skip"),
            db=db, current_client=client,
        )

    result = decide()
    db.refresh(proposal)
    if decision == "approve":
        assert proposal.status == "posted"
        assert proposal.posted_transaction_id == result["id"]
        assert _counts(db) == (2, 4, 1)
    else:
        assert result is proposal
        assert proposal.status == "rejected"
        assert proposal.note == "Skip"
        assert _counts(db) == (1, 2, 1)
    before = _counts(db)
    with pytest.raises(HTTPException) as exc:
        decide()
    assert exc.value.status_code == 400
    assert _counts(db) == before


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize("missing", ["unknown_id", "other_client"])
def test_proposal_handlers_return_404_without_changing_missing_or_other_client_proposals(posting, decision, missing):
    db, client, cash, food, reserve = posting
    _rule(posting)
    workflow.record_entry(db, client.id, _payload(posting))
    proposal = db.query(models.TransactionProposal).one()
    proposal_id = 999999 if missing == "unknown_id" else proposal.id
    if missing == "other_client":
        client = models.Client(id=2, name="other", ai_config={}, general_settings={})
        db.add(client)
        db.commit()
    before = _counts(db)
    balances = (calculate_account_valued_balance(db, cash), calculate_account_valued_balance(db, food), calculate_account_valued_balance(db, reserve))
    with pytest.raises(HTTPException) as exc:
        if decision == "approve":
            router.approve_proposal(proposal_id, db=db, current_client=client)
        else:
            router.reject_proposal(
                proposal_id, schemas.TransactionProposalDecision(note="Skip"),
                db=db, current_client=client,
            )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Transaction proposal not found"
    assert _counts(db) == before
    assert proposal.status == "pending"
    assert (calculate_account_valued_balance(db, cash), calculate_account_valued_balance(db, food), calculate_account_valued_balance(db, reserve)) == balances


def test_proposal_approval_rolls_back_posting_and_decision_when_journal_posting_fails(posting, monkeypatch):
    db, client, *_ = posting
    _rule(posting)
    workflow.record_entry(db, client.id, _payload(posting))
    proposal = db.query(models.TransactionProposal).one()

    def fail_posting(*_args, **_kwargs):
        raise ValueError("forced journal failure")

    monkeypatch.setattr(ledger, "_post_transaction_journal", fail_posting)
    with pytest.raises(HTTPException) as exc:
        router.approve_proposal(proposal.id, db=db, current_client=client)
    assert exc.value.status_code == 400
    assert exc.value.detail == "forced journal failure"
    assert _counts(db) == (1, 2, 1)
    db.refresh(proposal)
    assert proposal.status == "pending"
    assert proposal.posted_transaction_id is None
