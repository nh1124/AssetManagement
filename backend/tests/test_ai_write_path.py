from __future__ import annotations

from datetime import date

import pytest

from backend.app import models, schemas
from backend.app.domain.money import Money
from backend.app.routers.transactions import approve_proposal as approve_proposal_endpoint
from backend.app.services.ai_policy_service import replace_client_policies
from backend.app.workflows.ai_change_request_workflow import (
    apply_change_request,
    approve_change_request,
    create_change_request,
)
from backend.app.workflows.transaction_approval_workflow import approve_transaction_proposal
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


def _approved_request(db, payload, *, risk="medium"):
    request = create_change_request(
        db,
        1,
        1,
        schemas.AiChangeRequestCreate(
            resource="transactions",
            action="create",
            risk=risk,
            input_payload=payload,
        ),
    )
    return approve_change_request(db, 1, 1, request.id)


def _capsule_rule(db, cash, destination):
    capsule = models.Capsule(
        client_id=1,
        name="Savings",
        target_amount=5000,
        monthly_contribution=0,
        account_id=destination.id,
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
        amount_value=300,
        is_active=True,
    )
    db.add(rule)
    db.commit()
    return capsule, rule


def test_default_approved_ai_create_queues_pending_proposal_and_marks_request_applied(posting):
    db, cash, destination, _ = posting
    request = _approved_request(db, _payload(cash, destination))

    applied = apply_change_request(db, 1, 1, request.id)

    proposal = db.query(models.TransactionProposal).one()
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0
    assert proposal.status == "pending"
    assert proposal.origin == "ai"
    assert proposal.origin_ref == {"change_request_id": request.id}
    assert applied.result == {"proposal_id": proposal.id, "queued": True}
    assert applied.status == "applied"
    assert cash.balance == 10000
    assert destination.balance == 0


@pytest.mark.parametrize("explicit_legs", [False, True], ids=["from-to-shorthand", "explicit-legs"])
def test_queued_proposal_preserves_requested_amount_and_resolved_legs(posting, explicit_legs):
    db, cash, destination, _ = posting
    payload = _payload(cash, destination)
    expected_legs = [
        {"account_id": destination.id, "debit": 1200.0, "credit": 0.0, "memo": None},
        {"account_id": cash.id, "debit": 0.0, "credit": 1200.0, "memo": None},
    ]
    if explicit_legs:
        expected_legs = [
            {"account_id": cash.id, "debit": 0.0, "credit": 1200.0, "memo": "Funding"},
            {"account_id": destination.id, "debit": 1200.0, "credit": 0.0, "memo": "Saving"},
        ]
        payload["legs"] = expected_legs
        payload["from_account_id"], payload["to_account_id"] = destination.id, cash.id
    request = _approved_request(db, payload)

    apply_change_request(db, 1, 1, request.id)
    db.expire_all()

    proposal = db.query(models.TransactionProposal).one()
    assert proposal.amount == payload["amount"]
    assert proposal.legs == [{**leg,
        "debit": Money.from_major(str(leg["debit"]), payload["currency"]).minor,
        "credit": Money.from_major(str(leg["credit"]), payload["currency"]).minor,
    } for leg in expected_legs]
    assert proposal.date == date(2026, 10, 11)
    assert proposal.description == payload["description"]
    assert proposal.currency == payload["currency"]


def test_allow_execute_at_request_risk_posts_directly_without_ai_proposal(posting):
    db, cash, destination, _ = posting
    request = _approved_request(db, _payload(cash, destination), risk="high")
    replace_client_policies(db, 1, [{
        "resource": "transactions",
        "action": "create",
        "risk": "high",
        "mode": "allow_execute",
    }])

    applied = apply_change_request(db, 1, 1, request.id)

    transaction = db.query(models.Transaction).one()
    assert db.query(models.TransactionProposal).count() == 0
    assert applied.result == {"transaction_id": transaction.id, "queued": False}
    assert applied.status == "applied"
    assert transaction.amount == 1200
    assert sorted((entry.account_id, entry.debit, entry.credit) for entry in transaction.journal_entries) == sorted([
        (cash.id, 0, 1200), (destination.id, 1200, 0),
    ])


def test_approving_ai_proposal_posts_and_queues_triggered_capsule_reservation(posting):
    db, cash, destination, _ = posting
    capsule, rule = _capsule_rule(db, cash, destination)
    request = _approved_request(db, _payload(cash, destination))
    apply_change_request(db, 1, 1, request.id)
    proposal = db.query(models.TransactionProposal).one()
    assert db.query(models.Transaction).count() == 0

    response = approve_proposal_endpoint(
        proposal.id,
        db=db,
        current_client=db.get(models.Client, 1),
    )

    transaction = db.query(models.Transaction).one()
    reservation = db.query(models.TransactionProposal).filter_by(origin="capsule").one()
    assert response["id"] == transaction.id
    assert proposal.status == "posted"
    assert proposal.posted_transaction_id == transaction.id
    assert reservation.status == "pending"
    assert reservation.origin_ref == {"capsule_id": capsule.id, "rule_id": rule.id}
    assert reservation.trigger_transaction_id == transaction.id
    assert reservation.amount == 300
    assert db.query(models.TransactionProposal).count() == 2
    assert db.query(models.JournalEntry).count() == 2


def test_approving_capsule_origin_proposal_does_not_queue_another_reservation(posting):
    db, cash, destination, _ = posting
    capsule, rule = _capsule_rule(db, cash, destination)
    proposal = _propose(
        db,
        cash,
        destination,
        origin_ref={"capsule_id": capsule.id, "rule_id": rule.id},
    )
    db.commit()

    transaction = approve_transaction_proposal(db, proposal, actor_client_id=1)
    db.flush()

    assert proposal.status == "posted"
    assert db.query(models.Transaction).one() is transaction
    assert db.query(models.TransactionProposal).one() is proposal
    assert db.query(models.JournalEntry).count() == 2
    db.rollback()
    assert db.query(models.Transaction).count() == 0
    assert db.query(models.JournalEntry).count() == 0
    db.refresh(proposal)
    assert proposal.status == "pending"


def test_queued_apply_audit_result_records_proposal_and_queued_true(posting):
    db, cash, destination, _ = posting
    request = _approved_request(db, _payload(cash, destination))

    applied = apply_change_request(db, 1, 1, request.id)

    log = db.query(models.AiAuditLog).filter_by(approval_request_id=request.id).order_by(
        models.AiAuditLog.id.desc(),
    ).first()
    assert log.result_summary == {
        "change_request_id": request.id,
        "status": "applied",
        "proposal_id": applied.result["proposal_id"],
        "queued": True,
    }
