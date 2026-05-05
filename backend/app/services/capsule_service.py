from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models


def capsule_balance(db: Session, capsule: models.Capsule) -> float:
    return sum(h.held_amount for h in capsule.holdings)


def remaining_target(db: Session, capsule: models.Capsule) -> float:
    return max(0.0, (capsule.target_amount or 0.0) - capsule_balance(db, capsule))


def upsert_capsule_holding(
    db: Session,
    capsule: models.Capsule,
    account_id: int,
    amount_delta: float,
    note: str | None = None,
) -> models.CapsuleHolding:
    holding = db.query(models.CapsuleHolding).filter(
        models.CapsuleHolding.capsule_id == capsule.id,
        models.CapsuleHolding.account_id == account_id,
    ).first()
    if holding:
        holding.held_amount = max(0.0, holding.held_amount + amount_delta)
        if note is not None:
            holding.note = note
    else:
        holding = models.CapsuleHolding(
            capsule_id=capsule.id,
            account_id=account_id,
            held_amount=max(0.0, amount_delta),
            note=note,
        )
        db.add(holding)
    db.flush()
    capsule.current_balance = capsule_balance(db, capsule)
    return holding


def capsule_to_dict(db: Session, capsule: models.Capsule) -> dict:
    balance = capsule_balance(db, capsule)
    capsule.current_balance = balance
    progress_pct = (balance / capsule.target_amount * 100) if capsule.target_amount else 0
    progress_pct = min(100, progress_pct)
    holdings = [
        {
            "id": h.id,
            "capsule_id": h.capsule_id,
            "account_id": h.account_id,
            "account_name": h.account.name if h.account else None,
            "held_amount": h.held_amount,
            "note": h.note,
            "updated_at": h.updated_at,
        }
        for h in capsule.holdings
    ]
    return {
        "id": capsule.id,
        "life_event_id": capsule.life_event_id,
        "name": capsule.name,
        "target_amount": capsule.target_amount,
        "monthly_contribution": capsule.monthly_contribution,
        "current_balance": balance,
        "account_id": capsule.account_id,
        "created_at": capsule.created_at,
        "progress_pct": round(progress_pct, 1),
        "holdings": holdings,
    }


def create_capsule_for_goal(db: Session, client_id: int, goal: models.LifeEvent) -> models.Capsule:
    existing = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id,
        models.Capsule.life_event_id == goal.id,
    ).first()
    if existing:
        return existing

    capsule = models.Capsule(
        client_id=client_id,
        life_event_id=goal.id,
        name=goal.name,
        target_amount=max(0.0, goal.target_amount or 0.0),
        monthly_contribution=0.0,
        current_balance=0.0,
        account_id=None,
    )
    db.add(capsule)
    db.flush()
    return capsule


def apply_capsule_rules_for_transaction(
    db: Session, transaction: models.Transaction
) -> list[models.CapsuleHolding]:
    if transaction.client_id is None:
        return []
    if transaction.category == "capsule_auto_allocation" or transaction.description.startswith("Capsule rule:"):
        return []

    rules = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.client_id == transaction.client_id,
        models.CapsuleRule.is_active.is_(True),
    ).all()
    updated: list[models.CapsuleHolding] = []

    for rule in rules:
        if not _rule_matches(rule, transaction):
            continue
        capsule = rule.capsule
        if not capsule:
            continue
        source_account_id = _resolve_rule_source_account_id(rule, transaction)
        if not source_account_id:
            continue
        amount = _resolve_rule_amount(rule, transaction)
        amount = min(amount, remaining_target(db, capsule))
        if amount <= 0:
            continue

        holding = upsert_capsule_holding(db, capsule, source_account_id, amount, note=f"Auto-allocated: {rule.trigger_type}")
        updated.append(holding)

    if updated:
        db.commit()
    return updated


def _rule_matches(rule: models.CapsuleRule, transaction: models.Transaction) -> bool:
    if rule.trigger_type != transaction.type:
        return False
    if rule.trigger_category:
        category = (transaction.category or "").lower()
        if rule.trigger_category.lower() not in category:
            return False
    if rule.trigger_description:
        description = (transaction.description or "").lower()
        if rule.trigger_description.lower() not in description:
            return False
    return True


def _resolve_rule_source_account_id(rule: models.CapsuleRule, transaction: models.Transaction) -> int | None:
    if rule.source_mode == "fixed_account":
        return rule.source_account_id
    if transaction.type == "Income":
        return transaction.to_account_id
    return transaction.from_account_id


def _resolve_rule_amount(rule: models.CapsuleRule, transaction: models.Transaction) -> float:
    value = max(0.0, rule.amount_value or 0.0)
    if rule.amount_type == "percentage":
        return max(0.0, (transaction.amount or 0.0) * value / 100.0)
    return value
