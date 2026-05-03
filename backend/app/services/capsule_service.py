from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from .. import models
from .accounting_service import calculate_account_journal_balance, process_transaction


def slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def create_capsule_account(db: Session, client_id: int, capsule_name: str) -> models.Account:
    candidate = unique_capsule_account_name(db, client_id, capsule_name)
    account = models.Account(
        client_id=client_id,
        name=candidate,
        account_type="asset",
        role=models.AccountRole.EARMARKED.value,
        balance=0.0,
        is_active=True,
    )
    db.add(account)
    db.flush()
    return account


def unique_capsule_account_name(
    db: Session,
    client_id: int,
    capsule_name: str,
    account_id: int | None = None,
) -> str:
    label = (capsule_name or "").strip() or "Fund"
    base = f"Capsule: {label}"
    candidate = base
    i = 2
    while True:
        query = db.query(models.Account).filter(
            models.Account.client_id == client_id,
            models.Account.name == candidate,
        )
        if account_id is not None:
            query = query.filter(models.Account.id != account_id)
        if not query.first():
            break
        candidate = f"{base} ({i})"
        i += 1
    return candidate


def ensure_capsule_account(db: Session, capsule: models.Capsule) -> models.Account:
    if capsule.account:
        capsule.account.is_active = True
        if capsule.account.name.startswith("capsule_"):
            capsule.account.name = unique_capsule_account_name(
                db,
                capsule.client_id,
                capsule.name,
                account_id=capsule.account.id,
            )
        return capsule.account
    if capsule.client_id is None:
        raise ValueError("capsule.client_id is required")
    account = create_capsule_account(db, capsule.client_id, capsule.name)
    capsule.account_id = account.id
    capsule.current_balance = 0.0
    db.flush()
    return account


def capsule_balance(db: Session, capsule: models.Capsule) -> float:
    if capsule.account:
        return calculate_account_journal_balance(db, capsule.account)
    return capsule.current_balance or 0.0


def remaining_target(db: Session, capsule: models.Capsule) -> float:
    return max(0.0, (capsule.target_amount or 0.0) - capsule_balance(db, capsule))


def capsule_to_dict(db: Session, capsule: models.Capsule) -> dict:
    account = ensure_capsule_account(db, capsule)
    balance = capsule_balance(db, capsule)
    capsule.current_balance = balance
    progress_pct = (balance / capsule.target_amount * 100) if capsule.target_amount else 0
    progress_pct = min(100, progress_pct)
    return {
        "id": capsule.id,
        "life_event_id": capsule.life_event_id,
        "name": capsule.name,
        "target_amount": capsule.target_amount,
        "monthly_contribution": capsule.monthly_contribution,
        "current_balance": balance,
        "account_id": account.id,
        "created_at": capsule.created_at,
        "progress_pct": round(progress_pct, 1),
    }


def create_capsule_for_goal(db: Session, client_id: int, goal: models.LifeEvent) -> models.Capsule:
    existing = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id,
        models.Capsule.life_event_id == goal.id,
    ).first()
    if existing:
        ensure_capsule_account(db, existing)
        _ensure_goal_allocation(db, goal.id, existing.account_id)
        return existing

    account = create_capsule_account(db, client_id, goal.name)
    capsule = models.Capsule(
        client_id=client_id,
        life_event_id=goal.id,
        name=goal.name,
        target_amount=max(0.0, goal.target_amount or 0.0),
        monthly_contribution=0.0,
        current_balance=0.0,
        account_id=account.id,
    )
    db.add(capsule)
    db.flush()
    _ensure_goal_allocation(db, goal.id, account.id)
    return capsule


def _ensure_goal_allocation(db: Session, life_event_id: int, account_id: int | None) -> None:
    if not account_id:
        return
    existing = db.query(models.GoalAllocation).filter(
        models.GoalAllocation.life_event_id == life_event_id,
        models.GoalAllocation.account_id == account_id,
    ).first()
    if existing:
        existing.allocation_percentage = 100.0
        return
    db.add(
        models.GoalAllocation(
            life_event_id=life_event_id,
            account_id=account_id,
            allocation_percentage=100.0,
        )
    )


def apply_capsule_rules_for_transaction(db: Session, transaction: models.Transaction) -> list[models.Transaction]:
    if transaction.client_id is None:
        return []
    if transaction.category == "capsule_auto_allocation" or transaction.description.startswith("Capsule rule:"):
        return []

    rules = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.client_id == transaction.client_id,
        models.CapsuleRule.is_active.is_(True),
    ).all()
    created: list[models.Transaction] = []

    for rule in rules:
        if not _rule_matches(rule, transaction):
            continue
        capsule = rule.capsule
        if not capsule or not capsule.account_id:
            continue
        source_account_id = _resolve_rule_source_account_id(rule, transaction)
        if not source_account_id or source_account_id == capsule.account_id:
            continue
        amount = _resolve_rule_amount(rule, transaction)
        amount = min(amount, remaining_target(db, capsule))
        if amount <= 0:
            continue
        tx = models.Transaction(
            client_id=transaction.client_id,
            date=transaction.date or date.today(),
            description=f"Capsule rule: {capsule.name}",
            amount=amount,
            type="Transfer",
            from_account_id=source_account_id,
            to_account_id=capsule.account_id,
            currency=transaction.currency or "JPY",
            category="capsule_auto_allocation",
        )
        db.add(tx)
        db.flush()
        process_transaction(db, tx)
        db.refresh(tx)
        capsule.current_balance = capsule_balance(db, capsule)
        created.append(tx)

    if created:
        db.commit()
    return created


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
