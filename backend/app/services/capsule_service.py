from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from .product_reserve_service import product_reserve_values


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
    linked_products = [
        {
            "id": product.id,
            "name": product.name,
            "is_asset": product.is_asset,
            **product_reserve_values(product),
        }
        for product in db.query(models.Product)
        .filter(models.Product.client_id == capsule.client_id, models.Product.funding_capsule_id == capsule.id)
        .order_by(models.Product.name)
        .all()
    ]
    recommended_monthly = round(sum(item["recommended_monthly_reserve"] for item in linked_products), 0)
    return {
        "id": capsule.id,
        "life_event_id": capsule.life_event_id,
        "name": capsule.name,
        "target_amount": capsule.target_amount,
        "monthly_contribution": capsule.monthly_contribution,
        "current_balance": balance,
        "account_id": capsule.account_id,
        "capsule_type": capsule.capsule_type or "manual",
        "target_amount_source": capsule.target_amount_source or "manual",
        "monthly_contribution_source": capsule.monthly_contribution_source or "manual",
        "recommended_monthly_contribution": recommended_monthly,
        "linked_products": linked_products,
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
        existing.capsule_type = existing.capsule_type or "life_event"
        if existing.capsule_type == "manual":
            existing.capsule_type = "life_event"
        return existing

    capsule = models.Capsule(
        client_id=client_id,
        life_event_id=goal.id,
        name=goal.name,
        target_amount=max(0.0, goal.target_amount or 0.0),
        monthly_contribution=0.0,
        current_balance=0.0,
        account_id=None,
        capsule_type="life_event",
        target_amount_source="life_event",
        monthly_contribution_source="manual",
    )
    db.add(capsule)
    db.flush()
    return capsule


# What a rule's trigger_type describes, as a statement about the entry's legs:
# which side the triggering leg is on, what kind of account it is, and what has
# to be on the other side. The transaction's own type is not consulted.
_TRIGGER_LEGS: dict[str, tuple[str, set[str], set[str] | None]] = {
    "Income": ("credit", {"income"}, None),
    "Expense": ("debit", {"expense"}, {"asset", "item"}),
    "CreditExpense": ("debit", {"expense"}, {"liability"}),
    "Transfer": ("debit", {"asset", "item"}, {"asset", "item"}),
}


def _side_amount(entry: models.JournalEntry, side: str) -> float:
    return (entry.debit or 0.0) if side == "debit" else (entry.credit or 0.0)


def apply_capsule_rules_for_transaction(
    db: Session,
    transaction: models.Transaction,
    *,
    commit: bool = True,
) -> list[models.CapsuleHolding]:
    """Reserve part of an account's balance for a capsule, per the client's rules.

    Called straight after the journal is posted and before the caller commits,
    so the legs are in the session but not yet written. The flush is what makes
    them readable; committing here would break the atomicity the posting path
    depends on (P5-002), which is why every caller passes commit=False.
    """
    if transaction.client_id is None:
        return []

    db.flush()
    entries = list(transaction.journal_entries)
    if not entries:
        return []
    accounts = {
        account.id: account
        for account in db.query(models.Account).filter(
            models.Account.id.in_({entry.account_id for entry in entries}),
        ).all()
    }

    rules = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.client_id == transaction.client_id,
        models.CapsuleRule.is_active.is_(True),
    ).all()
    updated: list[models.CapsuleHolding] = []

    for rule in rules:
        triggered = _triggered_legs(rule, transaction, entries, accounts)
        if not triggered:
            continue
        capsule = rule.capsule
        if not capsule:
            continue
        source_account_id = _resolve_rule_source_account_id(rule, entries, triggered[0])
        if not source_account_id:
            continue
        amount = _resolve_rule_amount(rule, transaction)
        amount = min(amount, remaining_target(db, capsule))
        if amount <= 0:
            continue

        holding = upsert_capsule_holding(db, capsule, source_account_id, amount, note=f"Auto-allocated: {rule.trigger_type}")
        updated.append(holding)

    if updated and commit:
        db.commit()
    return updated


def _triggered_legs(
    rule: models.CapsuleRule,
    transaction: models.Transaction,
    entries: list[models.JournalEntry],
    accounts: dict[int, models.Account],
) -> list[models.JournalEntry]:
    """The legs of this transaction that the rule's trigger describes."""
    spec = _TRIGGER_LEGS.get(rule.trigger_type)
    if spec is None:
        return []
    side, account_types, funding_types = spec
    other = "credit" if side == "debit" else "debit"

    if rule.trigger_description:
        if rule.trigger_description.lower() not in (transaction.description or "").lower():
            return []

    if funding_types is not None:
        funded_as_expected = any(
            _side_amount(entry, other) > 0
            and (accounts.get(entry.account_id) is not None)
            and accounts[entry.account_id].account_type in funding_types
            for entry in entries
        )
        if not funded_as_expected:
            return []

    needle = (rule.trigger_category or "").strip().lower()
    matched: list[models.JournalEntry] = []
    for entry in entries:
        if _side_amount(entry, side) <= 0:
            continue
        account = accounts.get(entry.account_id)
        if account is None or account.account_type not in account_types:
            continue
        if needle and needle != (account.name or "").strip().lower():
            continue
        matched.append(entry)

    matched.sort(key=lambda entry: _side_amount(entry, side), reverse=True)
    return matched


def _resolve_rule_source_account_id(
    rule: models.CapsuleRule,
    entries: list[models.JournalEntry],
    triggered: models.JournalEntry,
) -> int | None:
    """Which account's balance the reservation is taken out of."""
    if rule.source_mode == "fixed_account":
        return rule.source_account_id

    # transaction_account: the other side of the triggering leg. A compound
    # entry has more than one, and picking one would be a guess, so the rule is
    # skipped instead -- fixed_account is how to say which account you mean.
    other = "credit" if (triggered.debit or 0.0) > 0 else "debit"
    candidates = [
        entry for entry in entries
        if entry is not triggered and _side_amount(entry, other) > 0
    ]
    if len(candidates) != 1:
        return None
    return candidates[0].account_id


def _resolve_rule_amount(rule: models.CapsuleRule, transaction: models.Transaction) -> float:
    """A percentage applies to the whole payment, not to the triggering leg.

    "10% of my salary" means the gross, so a payroll entry split across a bank
    account, a savings plan and a stock plan is measured on its total.
    """
    value = max(0.0, rule.amount_value or 0.0)
    if rule.amount_type == "percentage":
        return max(0.0, (transaction.amount or 0.0) * value / 100.0)
    return value
