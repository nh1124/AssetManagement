from __future__ import annotations

from backend.app.domain.money import Money

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from backend.app import models
    from backend.app.database import Base
    from backend.app.services.ledger_service import (
        Leg, approve_proposal, list_proposals, propose_transaction, reject_proposal,
    )
except ModuleNotFoundError:
    from app import models  # type: ignore[no-redef]
    from app.database import Base  # type: ignore[no-redef]
    from app.services.ledger_service import (  # type: ignore[no-redef]
        Leg, approve_proposal, list_proposals, propose_transaction, reject_proposal,
    )


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


@pytest.fixture
def posting():
    db = _session()
    client = models.Client(
        id=1,
        name="transaction-proposal-test",
        general_settings={},
        ai_config={},
    )
    other_client = models.Client(
        id=2,
        name="other-client",
        general_settings={},
        ai_config={},
    )
    cash = models.Account(
        client_id=1,
        name="Cash",
        account_type="asset",
        balance=10000,
    )
    capsule = models.Account(
        client_id=1,
        name="Capsule",
        account_type="asset",
        balance=0,
    )
    other_account = models.Account(
        client_id=2,
        name="Other cash",
        account_type="asset",
        balance=0,
    )
    db.add_all([client, other_client, cash, capsule, other_account])
    db.commit()
    try:
        yield db, cash, capsule, other_account
    finally:
        db.close()


def _propose(db, cash, capsule, **kwargs):
    data = {
        "origin": "capsule",
        "origin_ref": {"capsule_id": 11, "rule_id": 3},
        "date": date(2026, 10, 11),
        "description": "Reserve savings",
        "amount": 1000,
        "legs": [
            Leg(
                account_id=capsule.id,
                debit=1000,
                memo="Reservation",
            ),
            Leg(
                account_id=cash.id,
                credit=1000,
            ),
        ],
    }
    data.update(kwargs)
    currency = data.get("currency", "JPY")
    data["amount_minor"] = Money.from_major(str(data.pop("amount")), currency).minor
    data["legs"] = [Leg(leg.account_id,
        Money.from_major(str(leg.debit), currency).minor,
        Money.from_major(str(leg.credit), currency).minor, leg.memo) for leg in data["legs"]]
    return propose_transaction(db, 1, **data)


def _assert_empty_ledger(db):
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0


def test_proposal_queues_without_posting_and_round_trips_legs(posting):
    db, cash, capsule, _ = posting
    proposal = _propose(db, cash, capsule)
    proposal_id = proposal.id
    db.expire_all()
    proposal = db.query(models.TransactionProposal).one()
    assert proposal.id == proposal_id
    assert proposal.status == "pending"
    assert proposal.legs == [
        {"account_id": capsule.id, "debit": 1000.0, "credit": 0.0, "memo": "Reservation"},
        {"account_id": cash.id, "debit": 0.0, "credit": 1000.0, "memo": None},
    ]
    assert cash.balance == 10000
    assert capsule.balance == 0
    _assert_empty_ledger(db)
    db.rollback()
    assert db.query(models.TransactionProposal).count() == 0


def test_approval_posts_described_transaction_and_legs(posting):
    db, cash, capsule, _ = posting
    proposal = _propose(db, cash, capsule, currency="USD")
    tx = approve_proposal(db, proposal, actor_client_id=1)
    db.flush()
    assert db.query(models.Transaction).one() is tx
    assert (tx.client_id, tx.date, tx.description, tx.amount, tx.currency) == (
        1, date(2026, 10, 11), "Reserve savings", 1000, "USD",
    )
    entries = db.query(models.JournalEntry).order_by(models.JournalEntry.sort_order).all()
    assert [(row.transaction_id, row.account_id, row.debit, row.credit, row.memo) for row in entries] == [
        (tx.id, capsule.id, 1000, 0, "Reservation"),
        (tx.id, cash.id, 0, 1000, None),
    ]
    assert proposal.status == "posted"
    assert proposal.posted_transaction_id == tx.id
    assert proposal.decided_at is not None
    assert proposal.decided_by_client_id == 1
    assert cash.balance == 9000
    assert capsule.balance == 1000
    db.rollback()
    _assert_empty_ledger(db)


def test_rejection_keeps_ledger_empty_and_sets_note(posting):
    db, cash, capsule, _ = posting
    proposal = _propose(db, cash, capsule)
    reject_proposal(db, proposal, actor_client_id=1, note="Skip this reservation")
    db.flush()
    db.expire_all()
    proposal = db.query(models.TransactionProposal).one()
    assert proposal.status == "rejected"
    assert proposal.note == "Skip this reservation"
    assert proposal.posted_transaction_id is None
    assert proposal.decided_at is not None
    assert proposal.decided_by_client_id == 1
    _assert_empty_ledger(db)


def test_approving_twice_raises_without_second_transaction(posting):
    db, cash, capsule, _ = posting
    proposal = _propose(db, cash, capsule)
    approve_proposal(db, proposal, actor_client_id=1)
    with pytest.raises(ValueError, match="not pending.*posted"):
        approve_proposal(db, proposal, actor_client_id=1)
    db.flush()
    assert db.query(models.Transaction).count() == 1
    assert db.query(models.JournalEntry).count() == 2


def test_rejecting_posted_proposal_raises(posting):
    db, cash, capsule, _ = posting
    proposal = _propose(db, cash, capsule)
    tx = approve_proposal(db, proposal, actor_client_id=1)
    with pytest.raises(ValueError, match="not pending.*posted"):
        reject_proposal(db, proposal, actor_client_id=1, note="Too late")
    db.flush()
    assert proposal.status == "posted"
    assert proposal.note is None
    assert db.query(models.Transaction).one() is tx
    assert db.query(models.JournalEntry).count() == 2


def test_idempotency_returns_same_row_even_after_rejection(posting):
    db, cash, capsule, _ = posting
    proposal = _propose(db, cash, capsule)
    assert _propose(db, cash, capsule, origin_ref={"rule_id": 3, "capsule_id": 11}) is proposal
    assert len(proposal.idempotency_key) == 64
    assert db.query(models.TransactionProposal).count() == 1
    reject_proposal(db, proposal, actor_client_id=1)
    assert _propose(db, cash, capsule) is proposal
    db.flush()
    assert db.query(models.TransactionProposal).count() == 1
    assert proposal.status == "rejected"
    _assert_empty_ledger(db)


def test_unbalanced_legs_raise_before_queueing(posting):
    db, cash, capsule, _ = posting
    with pytest.raises(ValueError, match="does not balance"):
        _propose(db, cash, capsule, legs=[
            Leg(
                account_id=capsule.id,
                debit=1000,
            ),
            Leg(
                account_id=cash.id,
                credit=900,
            ),
        ])
    db.flush()
    assert db.query(models.TransactionProposal).count() == 0
    _assert_empty_ledger(db)


def test_other_clients_account_raises_before_queueing(posting):
    db, cash, capsule, other_account = posting
    with pytest.raises(ValueError, match=f"Account {other_account.id} not found for this client"):
        _propose(db, cash, capsule, legs=[
            Leg(
                account_id=other_account.id,
                debit=1000,
            ),
            Leg(
                account_id=cash.id,
                credit=1000,
            ),
        ])
    db.flush()
    assert db.query(models.TransactionProposal).count() == 0
    _assert_empty_ledger(db)


def test_list_proposals_filters_status_origin_and_client_newest_first(posting):
    db, cash, capsule, other_account = posting
    first = _propose(db, cash, capsule, idempotency_key="first")
    second = _propose(db, cash, capsule, origin="mcp", idempotency_key="second")
    third = _propose(db, cash, capsule, idempotency_key="third")
    propose_transaction(
        db,
        2,
        origin="capsule",
        date=date(2026, 10, 11),
        description="Other client's proposal",
        amount_minor=Money.from_major(str(1000), "JPY").minor,
        legs=[
            Leg(
                account_id=other_account.id,
                debit=1000,
            ),
            Leg(
                account_id=other_account.id,
                credit=1000,
            ),
        ],
        idempotency_key="first",
    )
    reject_proposal(db, first, actor_client_id=1)
    db.flush()
    assert list_proposals(db, 1) == [third, second, first]
    assert list_proposals(db, 1, status="pending") == [third, second]
    assert list_proposals(db, 1, status="rejected") == [first]
    assert list_proposals(db, 1, origin="capsule") == [third, first]
    assert list_proposals(db, 1, status="pending", origin="capsule") == [third]
    _assert_empty_ledger(db)
