"""Preserve the AI post-time capsule chain when posting moves to approval.

L1 ledger_service cannot call the higher-layer capsule service, so their
combination belongs here. Capsule reservations must not trigger their own rules.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from ..services.ledger_service import approve_proposal
from ..services.capsule_service import apply_capsule_rules_for_transaction


def approve_transaction_proposal(
    db: Session,
    proposal: models.TransactionProposal,
    *,
    actor_client_id: int,
) -> models.Transaction:
    transaction = approve_proposal(db, proposal, actor_client_id=actor_client_id)
    # Preserve the pre-H7 AI post-time rules, but a capsule reservation must
    # not re-trigger the rules that produced it.
    if proposal.origin != "capsule":
        apply_capsule_rules_for_transaction(db, transaction, commit=False)
    return transaction
