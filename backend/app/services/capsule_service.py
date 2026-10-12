from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP
from fractions import Fraction
from typing import Protocol, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..domain.errors import Invalid, NotFound
from ..domain.money import Money
from . import ledger_service
from .cache_service import invalidate_client
from .fx_service import get_client_currency
from .product_reserve_service import product_reserve_values


# Holdings-based balances and their cache are retired by capsule_design_review.md §7.6 (H6).
def capsule_balance(db: Session, capsule: models.Capsule) -> float:
    return sum(h.held_amount for h in capsule.holdings)


def remaining_target(db: Session, capsule: models.Capsule) -> float:
    return max(0.0, (capsule.target_amount or 0.0) - capsule_balance(db, capsule))


def total_held_amount_for_account(db: Session, account_id: int) -> float:
    # capsule_design_review.md §7.6 retires holdings, so this aggregate retires with them.
    return db.query(func.coalesce(func.sum(models.CapsuleHolding.held_amount), 0.0)).filter(
        models.CapsuleHolding.account_id == account_id,
    ).scalar() or 0.0


def get_capsule(db: Session, client_id: int, capsule_id: int) -> models.Capsule | None:
    return db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == client_id,
    ).first()


def get_product_funding_capsule(db: Session, client_id: int, capsule_id: int) -> models.Capsule | None:
    # Product reserves must belong to their client and cannot use a goal capsule.
    return db.query(models.Capsule).filter(
        models.Capsule.id == capsule_id,
        models.Capsule.client_id == client_id,
        models.Capsule.life_event_id.is_(None),
    ).first()


def list_capsules(db: Session, client_id: int, skip: int = 0, limit: int = 100) -> list[models.Capsule]:
    return db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id,
    ).offset(skip).limit(limit).all()


def list_capsule_details(
    db: Session, client_id: int, skip: int = 0, limit: int = 100, *, commit: bool = True,
) -> list[dict]:
    result = [capsule_to_dict(db, capsule) for capsule in list_capsules(db, client_id, skip, limit)]
    # Serialization updates the legacy cache; keep the original GET commit boundary.
    if commit:
        db.commit()
    else:
        db.flush()
    return result


def _finish_write(db: Session, client_id: int, record=None, *, commit: bool) -> None:
    if commit:
        db.commit()
        if record is not None:
            db.refresh(record)
        invalidate_client(client_id)
    else:
        db.flush()


def create_capsule(
    db: Session, client_id: int, payload: schemas.CapsuleCreate, *, commit: bool = True,
) -> models.Capsule:
    capsule = models.Capsule(
        client_id=client_id,
        life_event_id=payload.life_event_id,
        name=payload.name,
        target_amount=max(0.0, payload.target_amount or 0.0),
        monthly_contribution=max(0.0, payload.monthly_contribution or 0.0),
        # This cache column is slated for removal in capsule_design_review.md §7.6.
        current_balance=0.0,
        account_id=payload.account_id,
        auto_post=payload.auto_post,
        capsule_type=payload.capsule_type or "manual",
        target_amount_source=payload.target_amount_source or "manual",
        monthly_contribution_source=payload.monthly_contribution_source or "manual",
    )
    db.add(capsule)
    _finish_write(db, client_id, capsule, commit=commit)
    return capsule


def update_capsule(
    db: Session, client_id: int, capsule_id: int, patch: schemas.CapsuleUpdate,
    *, commit: bool = True,
) -> models.Capsule | None:
    capsule = get_capsule(db, client_id, capsule_id)
    if capsule is None:
        return None
    for key, value in patch.model_dump(exclude_unset=True).items():
        if key == "current_balance":
            continue
        elif key == "target_amount":
            capsule.target_amount = max(0.0, value or 0.0)
        elif key == "monthly_contribution":
            capsule.monthly_contribution = max(0.0, value or 0.0)
        elif key in {"capsule_type", "target_amount_source", "monthly_contribution_source"}:
            setattr(capsule, key, value or "manual")
        else:
            setattr(capsule, key, value)
    # Holdings-based cache refresh is retired by capsule_design_review.md §7.6 (H6).
    capsule.current_balance = capsule_balance(db, capsule)
    _finish_write(db, client_id, capsule, commit=commit)
    return capsule


def delete_capsule(db: Session, client_id: int, capsule_id: int, *, commit: bool = True) -> bool:
    capsule = get_capsule(db, client_id, capsule_id)
    if capsule is None:
        return False
    if capsule.life_event_id:
        raise Invalid("LifeEvent capsules are managed by their LifeEvent and cannot be deleted directly")
    linked_products = db.query(models.Product.id).filter(
        models.Product.client_id == client_id,
        models.Product.funding_capsule_id == capsule.id,
    ).first()
    if linked_products:
        raise Invalid("Capsules linked to Product/Item reserves cannot be deleted while products use them")
    db.delete(capsule)
    _finish_write(db, client_id, commit=commit)
    return True


def list_rules(db: Session, client_id: int) -> list[models.CapsuleRule]:
    return db.query(models.CapsuleRule).filter(
        models.CapsuleRule.client_id == client_id,
    ).order_by(models.CapsuleRule.id).all()


def create_rule(
    db: Session, client_id: int, payload: schemas.CapsuleRuleCreate, *, commit: bool = True,
) -> models.CapsuleRule:
    if get_capsule(db, client_id, payload.capsule_id) is None:
        raise NotFound("Capsule not found")
    if payload.source_account_id:
        account = db.query(models.Account).filter(
            models.Account.id == payload.source_account_id,
            models.Account.client_id == client_id,
        ).first()
        if not account:
            raise NotFound("Source account not found")
    rule = models.CapsuleRule(**payload.model_dump(), client_id=client_id)
    db.add(rule)
    _finish_write(db, client_id, rule, commit=commit)
    return rule


def update_rule(
    db: Session, client_id: int, rule_id: int, patch: schemas.CapsuleRuleUpdate,
    *, commit: bool = True,
) -> models.CapsuleRule | None:
    rule = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.id == rule_id,
        models.CapsuleRule.client_id == client_id,
    ).first()
    if rule is None:
        return None
    for key, value in patch.model_dump(exclude_unset=True).items():
        setattr(rule, key, value)
    _finish_write(db, client_id, rule, commit=commit)
    return rule


def delete_rule(db: Session, client_id: int, rule_id: int, *, commit: bool = True) -> bool:
    rule = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.id == rule_id,
        models.CapsuleRule.client_id == client_id,
    ).first()
    if rule is None:
        return False
    db.delete(rule)
    _finish_write(db, client_id, commit=commit)
    return True


# Holding CRUD preserves the claims slated for removal in capsule_design_review.md §7.6 (H6).
def list_holdings(db: Session, client_id: int, capsule_id: int) -> list[models.CapsuleHolding] | None:
    capsule = get_capsule(db, client_id, capsule_id)
    return list(capsule.holdings) if capsule is not None else None


def create_holding(
    db: Session, client_id: int, capsule_id: int, payload: schemas.CapsuleHoldingCreate,
    *, commit: bool = True,
) -> models.CapsuleHolding:
    if get_capsule(db, client_id, capsule_id) is None:
        raise NotFound("Capsule not found")
    account = db.query(models.Account).filter(
        models.Account.id == payload.account_id,
        models.Account.client_id == client_id,
    ).first()
    if not account:
        raise NotFound("Account not found")
    holding = db.query(models.CapsuleHolding).filter(
        models.CapsuleHolding.capsule_id == capsule_id,
        models.CapsuleHolding.account_id == payload.account_id,
    ).first()
    if holding:
        holding.held_amount = payload.held_amount
        holding.note = payload.note
    else:
        holding = models.CapsuleHolding(
            capsule_id=capsule_id, account_id=payload.account_id,
            held_amount=payload.held_amount, note=payload.note,
        )
        db.add(holding)
    _finish_write(db, client_id, holding, commit=commit)
    return holding


def update_holding(
    db: Session, client_id: int, capsule_id: int, holding_id: int, patch: schemas.CapsuleHoldingUpdate,
    *, commit: bool = True,
) -> models.CapsuleHolding | None:
    if get_capsule(db, client_id, capsule_id) is None:
        return None
    holding = db.query(models.CapsuleHolding).filter(
        models.CapsuleHolding.id == holding_id,
        models.CapsuleHolding.capsule_id == capsule_id,
    ).first()
    if holding is None:
        return None
    for key, value in patch.model_dump(exclude_unset=True).items():
        setattr(holding, key, value)
    _finish_write(db, client_id, holding, commit=commit)
    return holding


def delete_holding(
    db: Session, client_id: int, capsule_id: int, holding_id: int, *, commit: bool = True,
) -> bool:
    if get_capsule(db, client_id, capsule_id) is None:
        return False
    holding = db.query(models.CapsuleHolding).filter(
        models.CapsuleHolding.id == holding_id,
        models.CapsuleHolding.capsule_id == capsule_id,
    ).first()
    if holding is None:
        return False
    db.delete(holding)
    _finish_write(db, client_id, commit=commit)
    return True


# Legacy contributions still write claims until capsule_design_review.md §7.6 (H6).
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
        "auto_post": capsule.auto_post,
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


class CapsuleEntry(Protocol):
    account_id: int
    debit: float
    credit: float


def _side_amount(entry: CapsuleEntry, side: str) -> float:
    return (entry.debit or 0.0) if side == "debit" else (entry.credit or 0.0)


@dataclass
class CapsuleTransferSpec:
    capsule_id: int
    rule_id: int
    capsule_name: str
    source_account_id: int
    destination_account_id: int
    amount: float
    auto_post: bool


def capsule_transfer_specs(
    db: Session,
    client_id: int,
    *,
    entries: Sequence[CapsuleEntry],
    description: str | None,
    amount: float,
    currency: str | None = None,
) -> list[CapsuleTransferSpec]:
    """Evaluate entries exposing account_id, debit and credit, whether posted journal entries or unsaved draft legs."""
    # Preview must not flush unrelated pending changes or attach its draft legs.
    with db.no_autoflush:
        if currency is None:
            currency = get_client_currency(db, client_id)
        accounts = {
            account.id: account
            for account in db.query(models.Account).filter(
                models.Account.id.in_({entry.account_id for entry in entries}),
            ).all()
        }
        rules = db.query(models.CapsuleRule).filter(
            models.CapsuleRule.client_id == client_id,
            models.CapsuleRule.is_active.is_(True),
        ).all()
        specs = []
        for rule in rules:
            triggered = _triggered_legs(rule, description, entries, accounts)
            if not triggered:
                continue
            capsule = rule.capsule
            if not capsule or capsule.account_id is None:
                continue
            source_account_id = _resolve_rule_source_account_id(rule, entries, triggered[0])
            if source_account_id is None or source_account_id == capsule.account_id:
                continue
            # Holdings-based remaining_target still serves legacy contribute until H6;
            # the two definitions intentionally coexist for this wave.
            balance = ledger_service.calculate_account_journal_balance(db, capsule.account)
            reserved = min(
                _resolve_rule_amount(rule, amount, currency=currency),
                max(0.0, (capsule.target_amount or 0.0) - balance),
            )
            if reserved <= 0:
                continue
            specs.append(CapsuleTransferSpec(
                capsule_id=capsule.id,
                rule_id=rule.id,
                capsule_name=capsule.name,
                source_account_id=source_account_id,
                destination_account_id=capsule.account_id,
                amount=reserved,
                auto_post=capsule.auto_post,
            ))
        return specs


def apply_capsule_rules_for_transaction(
    db: Session,
    transaction: models.Transaction,
    *,
    commit: bool = True,
) -> list[models.TransactionProposal | models.Transaction]:
    """A reservation is now a ledger fact: post it or queue it, without a holding.

    Return what this transaction's rules resolved to, including existing proposals,
    rather than only newly written rows.

    Flush makes the trigger's legs visible while commit=False keeps the caller's
    posting and reservations in the same atomic transaction.
    """
    if transaction.client_id is None:
        return []
    db.flush()
    specs = capsule_transfer_specs(
        db,
        transaction.client_id,
        entries=list(transaction.journal_entries),
        description=transaction.description,
        amount=transaction.amount,
        currency=transaction.currency,
    )
    resolved = []
    for spec in specs:
        amount_minor = Money.from_major(str(spec.amount), transaction.currency).minor
        legs = ledger_service.simple_legs(
            amount_minor, spec.source_account_id, spec.destination_account_id,
        )
        columns = dict(
            date=transaction.date,
            description=f"Capsule reservation: {spec.capsule_name}",
            amount_minor=amount_minor,
            currency=transaction.currency,
            legs=legs,
        )
        if spec.auto_post:
            resolved.append(ledger_service.create_transaction(
                db, client_id=transaction.client_id, **columns,
            ))
        else:
            resolved.append(ledger_service.propose_transaction(
                db,
                transaction.client_id,
                origin="capsule",
                origin_ref={"capsule_id": spec.capsule_id, "rule_id": spec.rule_id},
                trigger_transaction_id=transaction.id,
                **columns,
            ))
    if resolved and commit:
        db.commit()
    return resolved


def _triggered_legs(
    rule: models.CapsuleRule,
    description: str | None,
    entries: Sequence[CapsuleEntry],
    accounts: dict[int, models.Account],
) -> list[CapsuleEntry]:
    """The legs of this transaction that the rule's trigger describes."""
    spec = _TRIGGER_LEGS.get(rule.trigger_type)
    if spec is None:
        return []
    side, account_types, funding_types = spec
    other = "credit" if side == "debit" else "debit"

    if rule.trigger_description:
        if rule.trigger_description.lower() not in (description or "").lower():
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
    matched: list[CapsuleEntry] = []
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
    entries: Sequence[CapsuleEntry],
    triggered: CapsuleEntry,
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


def _resolve_rule_amount(
    rule: models.CapsuleRule, amount: float, *, currency: str,
) -> float:
    """A percentage applies to the whole payment, not to the triggering leg.

    "10% of my salary" means the gross, so a payroll entry split across a bank
    account, a savings plan and a stock plan is measured on its total.
    """
    value = max(0.0, rule.amount_value or 0.0)
    if rule.amount_type == "percentage":
        base = Money.from_float(float(max(0.0, amount or 0.0)), currency, rounding=ROUND_HALF_UP)
        # The decimal representation preserves fractional percentages without float division.
        ratio = Fraction(Fraction(str(value)), 100)
        return base.scale(ratio, rounding=ROUND_HALF_UP).to_float()
    return value
