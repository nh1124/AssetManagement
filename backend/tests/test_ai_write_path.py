from __future__ import annotations

from app.services.money_storage import to_minor, rule_amount_fields


from datetime import date

import pytest

from backend.app import models, schemas
from backend.app.domain.money import Money
from backend.app.services.ai_policy_service import set_operation_mode
from backend.app.workflows.ai_change_request_workflow import (
    apply_change_request,
    approve_change_request,
    create_change_request,
)
from backend.app.workflows.ledger_entry_workflow import approve_entry_proposal
from test_transaction_proposals import _propose, posting


def _payload(cash, destination):
    return {
        "date": "2026-10-11",
        "description": "AI transfer",
        "amount": 1200,
        "currency": "USD",
        "from_account_id": cash.id,
        "to_account_id": destination.id,
    }


def _approved_request(db, payload):
    request = create_change_request(
        db,
        1,
        1,
        schemas.AiChangeRequestCreate(
            resource="transactions",
            action="create",
            input_payload=payload,
        ),
    )
    # Every approval is confirmed with the authenticator code (WP36).
    if db.query(models.ClientMfaSetting).filter_by(client_id=1).first() is None:
        db.add(models.ClientMfaSetting(client_id=1, enabled=True))
        db.commit()
    return approve_change_request(db, 1, 1, request.id, {"type": "step_up", "sub": "1"})


def _capsule_rule(db, cash, destination):
    capsule = models.Capsule(
        client_id=1,
        name="Savings",
        target_amount_minor=to_minor(5000, "JPY"),
        monthly_contribution_minor=to_minor(0, "JPY"),
        funding_sources=[models.CapsuleFundingSource(client_id=1, account_id=destination.id, target_amount_minor=to_minor(5000, "JPY") or 0)],
        auto_post=False,
    )
    db.add(capsule)
    db.flush()
    rule = models.CapsuleRule(
        client_id=1,
        capsule_id=capsule.id,
        trigger_type="Transfer",
        source_mode="fixed_account",
        source_account_id=cash.id,
        amount_type="fixed",
        **rule_amount_fields(300, "fixed", "JPY"),
        is_active=True,
    )
    db.add(rule)
    db.commit()
    return capsule, rule


@pytest.mark.parametrize("mode", [None, "approval", "allow"], ids=["default", "approval", "allow"])
def test_approved_ai_create_posts_directly_whatever_the_permission(posting, mode):
    """The person approved it with the authenticator code, so it never waits in 未反映 (WP38)."""
    db, cash, destination, _ = posting
    request = _approved_request(db, _payload(cash, destination))
    if mode is not None:
        set_operation_mode(db, 1, "transactions.create", mode, None)

    applied = apply_change_request(db, 1, 1, request.id)

    transaction = db.query(models.Transaction).one()
    assert db.query(models.TransactionProposal).count() == 0
    assert applied.result == {"transaction_id": transaction.id}
    assert applied.status == "applied"
    assert transaction.amount == 1200
    assert sorted((entry.account_id, entry.debit, entry.credit) for entry in transaction.journal_entries) == sorted([
        (cash.id, 0, 1200), (destination.id, 1200, 0),
    ])


@pytest.mark.parametrize("explicit_legs", [False, True], ids=["from-to-shorthand", "explicit-legs"])
def test_posted_transaction_keeps_requested_amount_and_resolved_legs(posting, explicit_legs):
    db, cash, destination, _ = posting
    payload = _payload(cash, destination)
    expected_legs = [
        (destination.id, 1200.0, 0.0, None),
        (cash.id, 0.0, 1200.0, None),
    ]
    if explicit_legs:
        payload["legs"] = [
            {"account_id": cash.id, "debit": 0.0, "credit": 1200.0, "memo": "Funding"},
            {"account_id": destination.id, "debit": 1200.0, "credit": 0.0, "memo": "Saving"},
        ]
        expected_legs = [(leg["account_id"], leg["debit"], leg["credit"], leg["memo"]) for leg in payload["legs"]]
        payload["from_account_id"], payload["to_account_id"] = destination.id, cash.id
    request = _approved_request(db, payload)

    apply_change_request(db, 1, 1, request.id)
    db.expire_all()

    transaction = db.query(models.Transaction).one()
    assert transaction.amount_minor == Money.from_major(str(payload["amount"]), payload["currency"]).minor
    assert sorted((entry.account_id, entry.debit, entry.credit, entry.memo) for entry in transaction.journal_entries) == sorted(expected_legs)
    assert transaction.date == date(2026, 10, 11)
    assert transaction.description == payload["description"]
    assert transaction.currency == payload["currency"]


def test_applying_ai_create_queues_the_capsule_reservation_it_triggers(posting):
    db, cash, destination, _ = posting
    capsule, rule = _capsule_rule(db, cash, destination)
    request = _approved_request(db, _payload(cash, destination))

    apply_change_request(db, 1, 1, request.id)

    transaction = db.query(models.Transaction).one()
    reservation = db.query(models.TransactionProposal).one()
    assert reservation.origin == "capsule"
    assert reservation.status == "pending"
    assert reservation.origin_ref == {"capsule_id": capsule.id, "rule_id": rule.id}
    assert reservation.trigger_transaction_id == transaction.id
    assert reservation.amount == 300
    assert db.query(models.JournalEntry).count() == 2


def test_approving_a_capsule_reservation_does_not_queue_another(posting):
    db, cash, destination, _ = posting
    capsule, rule = _capsule_rule(db, cash, destination)
    proposal = _propose(
        db,
        cash,
        destination,
        origin_ref={"capsule_id": capsule.id, "rule_id": rule.id},
    )
    db.commit()

    transaction = approve_entry_proposal(db, 1, proposal.id)

    assert proposal.status == "posted"
    assert db.query(models.Transaction).one() == transaction
    assert db.query(models.TransactionProposal).one() == proposal
    assert db.query(models.JournalEntry).count() == 2


def test_apply_audit_result_records_the_posted_transaction(posting):
    db, cash, destination, _ = posting
    request = _approved_request(db, _payload(cash, destination))

    applied = apply_change_request(db, 1, 1, request.id)

    log = db.query(models.AiAuditLog).filter_by(approval_request_id=request.id).order_by(
        models.AiAuditLog.id.desc(),
    ).first()
    assert log.result_summary == {
        "change_request_id": request.id,
        "status": "applied",
        "transaction_id": applied.result["transaction_id"],
    }
