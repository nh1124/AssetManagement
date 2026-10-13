from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as Date
from decimal import ROUND_HALF_UP
from fractions import Fraction
from typing import Protocol, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from .money_storage import to_minor, money_client_currency, rule_amount_fields, rule_data

from .. import models, schemas
from ..domain.errors import Invalid, NotFound
from ..domain.money import Money
from ..domain.journal import Leg
from . import ledger_service
from .cache_service import invalidate_client
from .fx_service import get_client_currency
from .product_reserve_service import product_reserve_values


def capsule_balance(db: Session, capsule: models.Capsule) -> float:
    currency = money_client_currency(db, capsule.client_id)
    return Money(claimed_minor(db, capsule.client_id, capsule.id).get(currency, 0), currency).to_float()


def remaining_target(db: Session, capsule: models.Capsule) -> float:
    return max(0.0, (capsule.target_amount or 0.0) - capsule_balance(db, capsule))


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
    db: Session, client_id: int, skip: int = 0, limit: int = 100,
) -> list[dict]:
    return [capsule_to_dict(db, capsule) for capsule in list_capsules(db, client_id, skip, limit)]


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
    if payload.account_id is not None and ledger_service.get_account(db, client_id, payload.account_id) is None:
        raise NotFound("Account not found")
    capsule = models.Capsule(
        client_id=client_id,
        life_event_id=payload.life_event_id,
        name=payload.name,
        target_amount_minor=to_minor(max(0.0, payload.target_amount or 0.0), money_client_currency(db, client_id)),
        monthly_contribution_minor=to_minor(max(0.0, payload.monthly_contribution or 0.0), money_client_currency(db, client_id)),
        auto_post=payload.auto_post,
        capsule_type=payload.capsule_type or "manual",
        target_amount_source=payload.target_amount_source or "manual",
        monthly_contribution_source=payload.monthly_contribution_source or "manual",
    )
    db.add(capsule)
    db.flush()
    if payload.account_id is not None:
        set_funding_sources(db, client_id, capsule.id, [schemas.CapsuleFundingSourceInput(
            account_id=payload.account_id, target_amount=capsule.target_amount or 0.0,
        )], commit=False)
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
        if key == "target_amount":
            capsule.target_amount_minor = to_minor(max(0.0, value or 0.0), money_client_currency(db, client_id))
        elif key == "monthly_contribution":
            capsule.monthly_contribution_minor = to_minor(max(0.0, value or 0.0), money_client_currency(db, client_id))
        elif key in {"capsule_type", "target_amount_source", "monthly_contribution_source"}:
            setattr(capsule, key, value or "manual")
        else:
            setattr(capsule, key, value)
    _finish_write(db, client_id, capsule, commit=commit)
    return capsule


def funding_source_to_dict(source: models.CapsuleFundingSource) -> dict:
    return {
        "id": source.id,
        "client_id": source.client_id,
        "capsule_id": source.capsule_id,
        "account_id": source.account_id,
        "account_name": source.account.name if source.account else None,
        "target_amount": source.target_amount,
        "max_share_bp": source.max_share_bp,
        "sort_order": source.sort_order,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


def list_funding_sources(
    db: Session, client_id: int, capsule_id: int,
) -> list[models.CapsuleFundingSource] | None:
    capsule = get_capsule(db, client_id, capsule_id)
    if capsule is None:
        return None
    return sorted(capsule.funding_sources, key=lambda source: (source.sort_order, source.id))


def drawdown_to_dict(drawdown: models.CapsuleDrawdown) -> dict:
    transaction = drawdown.transaction
    return {
        "id": drawdown.id, "client_id": drawdown.client_id,
        "capsule_id": drawdown.capsule_id, "transaction_id": drawdown.transaction_id,
        "kind": drawdown.kind, "amount_minor": drawdown.amount_minor,
        "amount": Money(drawdown.amount_minor, transaction.currency).to_float(),
        "currency": transaction.currency, "date": transaction.date,
        "description": transaction.description, "note": drawdown.note,
        "created_at": drawdown.created_at,
    }


def list_drawdowns(db: Session, client_id: int, capsule_id: int) -> list[models.CapsuleDrawdown]:
    if get_capsule(db, client_id, capsule_id) is None:
        raise Invalid("Capsule not found for this client")
    return db.query(models.CapsuleDrawdown).filter(
        models.CapsuleDrawdown.client_id == client_id,
        models.CapsuleDrawdown.capsule_id == capsule_id,
    ).order_by(models.CapsuleDrawdown.created_at.desc(), models.CapsuleDrawdown.id.desc()).all()


def record_drawdown(
    db: Session, client_id: int, capsule_id: int, *, amount: float,
    from_account_id: int, to_account_id: int, kind: str, date: Date,
    description: str, note: str | None = None, commit: bool = True,
) -> tuple[models.Transaction, models.CapsuleDrawdown]:
    # Serialize drawdowns of one capsule, including changes to its funding plan.
    capsule = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id, models.Capsule.id == capsule_id,
    ).with_for_update().first()
    if capsule is None:
        raise Invalid("Capsule not found for this client")
    for account_id in (from_account_id, to_account_id):
        if ledger_service.get_account(db, client_id, account_id) is None:
            raise Invalid(f"Account {account_id} not found for this client")
    if kind not in {"as_intended", "diverted"}:
        raise Invalid("Drawdown kind must be as_intended or diverted")
    currency = get_client_currency(db, client_id)
    try:
        money = Money.from_major(str(amount), currency)
    except (ValueError, ArithmeticError) as exc:
        raise Invalid("Drawdown amount must be a finite positive amount") from exc
    if money.minor <= 0:
        raise Invalid("Drawdown amount must be positive")
    if not any(source.account_id == from_account_id for source in capsule.funding_sources):
        raise Invalid("Source account is not a capsule funding source")
    claim = claimed_minor(db, client_id, capsule_id).get(currency, 0)
    if money.minor > claim:
        raise Invalid(f"Drawdown exceeds capsule claim of {Money(claim, currency).to_major()} {currency}")
    try:
        transaction = ledger_service.create_transaction(
            db, client_id=client_id, date=date, description=description,
            amount_minor=money.minor, currency=currency,
            legs=[Leg(to_account_id, debit=money.minor),
                  Leg(from_account_id, credit=money.minor, capsule_id=capsule_id)],
        )
        drawdown = models.CapsuleDrawdown(
            client_id=client_id, capsule_id=capsule_id, transaction_id=transaction.id,
            kind=kind, amount_minor=money.minor, note=note,
        )
        db.add(drawdown)
        _finish_write(db, client_id, drawdown, commit=commit)
        return transaction, drawdown
    except Exception:
        db.rollback()
        raise


def _percent(basis_points: int) -> str:
    """Basis points as a percentage, without a trailing zero it does not need."""
    text = f"{basis_points / 100:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def set_funding_sources(
    db: Session, client_id: int, capsule_id: int,
    payloads: Sequence[schemas.CapsuleFundingSourceInput], *, commit: bool = True,
) -> list[models.CapsuleFundingSource]:
    """Replace a capsule's intent atomically; this does not reserve or move money."""
    capsule = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id, models.Capsule.id == capsule_id,
    ).with_for_update().first()
    if capsule is None:
        raise NotFound("Capsule not found")
    account_ids = [payload.account_id for payload in payloads]
    if len(set(account_ids)) != len(account_ids):
        raise Invalid("Duplicate funding source account")
    # Serialize competing declarations on the same account, in a stable order.
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.id.in_(account_ids),
    ).order_by(models.Account.id).with_for_update().all()
    if {account.id for account in accounts} != set(account_ids):
        raise NotFound("Account not found")
    named_rule = db.query(models.CapsuleRule).filter(
        models.CapsuleRule.client_id == client_id,
        models.CapsuleRule.capsule_id == capsule_id,
        models.CapsuleRule.destination_account_id.is_not(None),
        models.CapsuleRule.destination_account_id.notin_(account_ids),
    ).order_by(models.CapsuleRule.id).first()
    if named_rule is not None:
        raise Invalid(f"Cannot remove account {named_rule.destination_account_id}: rule {named_rule.id} names it as its destination")
    other_shares = dict(db.query(
        models.CapsuleFundingSource.account_id,
        func.coalesce(func.sum(models.CapsuleFundingSource.max_share_bp), 0),
    ).filter(
        models.CapsuleFundingSource.client_id == client_id,
        models.CapsuleFundingSource.capsule_id != capsule_id,
        models.CapsuleFundingSource.account_id.in_(account_ids),
    ).group_by(models.CapsuleFundingSource.account_id).all())
    account_names = {account.id: account.name for account in accounts}
    for payload in payloads:
        total = other_shares.get(payload.account_id, 0) + (payload.max_share_bp or 0)
        if total > 10000:
            # Basis points are how the share is stored, not how it was asked for.
            # The message reaches a person who typed a percentage, so it answers
            # in percent and names the account they have to take it from.
            raise Invalid(
                f"Declared capsule shares for account {payload.account_id} "
                f"({account_names[payload.account_id]}) total {_percent(total)}%, "
                f"which is more than the account has"
            )
    currency = money_client_currency(db, client_id)
    # Complete validation/conversion before touching the saved plan.
    amounts = [to_minor(payload.target_amount, currency) for payload in payloads]
    existing = {source.account_id: source for source in capsule.funding_sources}
    sources = []
    for payload, amount in zip(payloads, amounts):
        source = existing.get(payload.account_id)
        if source is None:
            source = models.CapsuleFundingSource(
                client_id=client_id, account_id=payload.account_id,
            )
        source.target_amount_minor = amount
        source.max_share_bp = payload.max_share_bp
        source.sort_order = payload.sort_order
        sources.append(source)
    # Retain matching rows so INSERT cannot collide with a not-yet-deleted row.
    # delete-orphan removes the lines omitted from this replacement.
    capsule.funding_sources = sources
    _finish_write(db, client_id, commit=commit)
    return list_funding_sources(db, client_id, capsule_id)


@dataclass(frozen=True)
class CapsuleDeletion:
    """What deleting a capsule removed, and what it deliberately left behind."""

    capsule_id: int
    capsule_name: str | None
    rules_deleted: int
    retained_account_id: int | None
    retained_account_name: str | None


def delete_capsule(
    db: Session, client_id: int, capsule_id: int, *, commit: bool = True,
) -> CapsuleDeletion | None:
    """Remove the reservation and its rules. The money is not the capsule's to move.

    X7: this used to accept a transfer_account_id and ignore it, so the same
    argument meant "where to return the balance" on goal deletion and nothing
    at all here. The two are not the same operation. Deleting a goal deletes
    its capsules' accounts, which is why the balance has to go somewhere
    first; deleting a capsule leaves the account standing, so there is nothing
    to return and nowhere it would come from.

    What a capsule owns is the reservation: a target, a monthly figure and the
    rules that move money toward it. The account is a separate thing with its
    own journal history, and it outlives the capsule, so the caller is told
    which account it still has rather than asked where to empty it.
    """
    capsule = get_capsule(db, client_id, capsule_id)
    if capsule is None:
        return None
    if capsule.life_event_id:
        raise Invalid("LifeEvent capsules are managed by their LifeEvent and cannot be deleted directly")
    linked_products = db.query(models.Product.id).filter(
        models.Product.client_id == client_id,
        models.Product.funding_capsule_id == capsule.id,
    ).first()
    if linked_products:
        raise Invalid("Capsules linked to Product/Item reserves cannot be deleted while products use them")
    sources = list_funding_sources(db, client_id, capsule_id)
    # Preserve the single-account deletion summary using the first planned
    # account; every funding account stays untouched.
    account = sources[0].account if sources else None
    outcome = CapsuleDeletion(
        capsule_id=capsule.id,
        capsule_name=capsule.name,
        # The rules go with the capsule: the foreign key cascades, and a rule
        # without a destination has nothing to say.
        rules_deleted=db.query(models.CapsuleRule).filter(
            models.CapsuleRule.client_id == client_id,
            models.CapsuleRule.capsule_id == capsule.id,
        ).count(),
        retained_account_id=account.id if account is not None else None,
        retained_account_name=account.name if account is not None else None,
    )
    db.delete(capsule)
    _finish_write(db, client_id, commit=commit)
    return outcome


def list_rules(db: Session, client_id: int) -> list[models.CapsuleRule]:
    return db.query(models.CapsuleRule).filter(
        models.CapsuleRule.client_id == client_id,
    ).order_by(models.CapsuleRule.id).all()


def create_rule(
    db: Session, client_id: int, payload: schemas.CapsuleRuleCreate, *, commit: bool = True,
) -> models.CapsuleRule:
    capsule = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id, models.Capsule.id == payload.capsule_id,
    ).with_for_update().first()
    if capsule is None:
        raise NotFound("Capsule not found")
    _validate_rule_destination(db, client_id, capsule.id, payload.destination_account_id)
    if payload.source_account_id:
        account = db.query(models.Account).filter(
            models.Account.id == payload.source_account_id,
            models.Account.client_id == client_id,
        ).first()
        if not account:
            raise NotFound("Source account not found")
    rule = models.CapsuleRule(**rule_data(payload.model_dump(), money_client_currency(db, client_id)), client_id=client_id)
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
    data = patch.model_dump(exclude_unset=True)
    capsule_id = data.get("capsule_id", rule.capsule_id)
    capsule = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id, models.Capsule.id == capsule_id,
    ).with_for_update().first()
    if capsule is None:
        raise NotFound("Capsule not found")
    _validate_rule_destination(
        db, client_id, capsule_id,
        data.get("destination_account_id", rule.destination_account_id),
    )
    if "amount_type" in data or "amount_value" in data:
        value = data.pop("amount_value", rule.amount_value)
        data.update(rule_amount_fields(value, data.get("amount_type", rule.amount_type), money_client_currency(db, client_id)))
    for key, value in data.items():
        setattr(rule, key, value)
    _finish_write(db, client_id, rule, commit=commit)
    return rule


def _validate_rule_destination(db: Session, client_id: int, capsule_id: int, account_id: int | None) -> None:
    if account_id is not None and db.query(models.CapsuleFundingSource.id).filter(
        models.CapsuleFundingSource.client_id == client_id,
        models.CapsuleFundingSource.capsule_id == capsule_id,
        models.CapsuleFundingSource.account_id == account_id,
    ).first() is None:
        raise NotFound(f"Destination account {account_id} is not in capsule {capsule_id}'s funding plan")


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


def capsule_to_dict(db: Session, capsule: models.Capsule) -> dict:
    balance = capsule_balance(db, capsule)
    progress_pct = (balance / capsule.target_amount * 100) if capsule.target_amount else 0
    progress_pct = min(100, progress_pct)
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
        "auto_post": capsule.auto_post,
        "capsule_type": capsule.capsule_type or "manual",
        "target_amount_source": capsule.target_amount_source or "manual",
        "monthly_contribution_source": capsule.monthly_contribution_source or "manual",
        "recommended_monthly_contribution": recommended_monthly,
        "linked_products": linked_products,
        "created_at": capsule.created_at,
        "progress_pct": round(progress_pct, 1),
        "funding_sources": [
            funding_source_to_dict(source) for source in capsule.funding_sources
        ],
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
        target_amount_minor=to_minor(max(0.0, goal.target_amount or 0.0), money_client_currency(db, client_id)),
        monthly_contribution_minor=to_minor(0.0, money_client_currency(db, client_id)),
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
    amount_minor: int
    currency: str
    auto_post: bool

    @property
    def amount(self) -> float:
        # Major units are only the preview/API boundary, never the clamp.
        return Money(self.amount_minor, self.currency).to_float()


def _capsule_proposals(db: Session, client_id: int, capsule_id: int, status: str):
    return db.query(models.TransactionProposal).filter(
        models.TransactionProposal.client_id == client_id,
        models.TransactionProposal.origin == "capsule",
        models.TransactionProposal.origin_ref["capsule_id"].as_integer() == capsule_id,
        models.TransactionProposal.status == status,
    )


def claimed_minor(
    db: Session, client_id: int, capsule_id: int, account_id: int | None = None,
) -> dict[str, int]:
    """Net attributed journal movements, per currency in integer minor units.

    Credits release the earmark by subtracting from debits. Neither proposals
    nor the current funding plan determine which recorded movements belong:
    only the leg itself says so, which is why an account's balance is not a
    claim and two capsules can share one account.

    Per currency, and never totalled. A reservation triggered by a dollar
    payment is counted in cents, and adding those to yen is exactly the
    operation B5 removed from the account balance. Callers decide what to do
    with a currency they did not expect.
    """
    with db.no_autoflush:
        query = db.query(
            models.Transaction.currency,
            func.sum(models.JournalEntry.debit_minor - models.JournalEntry.credit_minor),
        ).join(
            models.Transaction, models.Transaction.id == models.JournalEntry.transaction_id,
        ).join(
            models.Capsule, models.Capsule.id == models.JournalEntry.capsule_id,
        ).filter(
            models.Transaction.client_id == client_id,
            models.Capsule.client_id == client_id,
            models.JournalEntry.capsule_id == capsule_id,
        )
        if account_id is not None:
            query = query.filter(models.JournalEntry.account_id == account_id)
        rows = query.group_by(models.Transaction.currency).all()
        return {currency: int(total) for currency, total in rows if total}


def account_claimed_minor(db: Session, client_id: int, account_id: int) -> dict[str, int]:
    """All capsules' net journal claims at an account, separately per currency."""
    rows = db.query(
        models.Transaction.currency,
        func.sum(models.JournalEntry.debit_minor - models.JournalEntry.credit_minor),
    ).join(models.Transaction, models.Transaction.id == models.JournalEntry.transaction_id).join(
        models.Capsule, models.Capsule.id == models.JournalEntry.capsule_id,
    ).filter(models.Transaction.client_id == client_id, models.Capsule.client_id == client_id,
             models.JournalEntry.account_id == account_id).group_by(models.Transaction.currency).all()
    return {currency: int(total) for currency, total in rows if total}


def _pending_claimed_minor(db: Session, client_id: int, capsule_id: int) -> dict[str, int]:
    # Pending is a decision outstanding, not a journal fact. Rejected proposals
    # enter neither query. The proposal already stores the exact reserved
    # amount, in its own currency, so this is grouped the same way.
    with db.no_autoflush:
        rows = _capsule_proposals(db, client_id, capsule_id, "pending").with_entities(
            models.TransactionProposal.currency,
            func.coalesce(func.sum(models.TransactionProposal.amount_minor), 0),
        ).group_by(models.TransactionProposal.currency).all()
        return {currency: int(total) for currency, total in rows if total}


def capsule_transfer_specs(
    db: Session,
    client_id: int,
    *,
    entries: Sequence[CapsuleEntry],
    description: str | None,
    amount: float,
    currency: str | None = None,
    amount_minor: int | None = None,
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
        client_currency = money_client_currency(db, client_id)
        rules = db.query(models.CapsuleRule).filter(
            models.CapsuleRule.client_id == client_id,
            models.CapsuleRule.is_active.is_(True),
        ).all()
        specs = []
        evaluated_minor: dict[int, int] = {}
        # A reservation is denominated in the triggering transaction's currency,
        # so the amount is computed there: a percentage keeps the payment's own
        # precision, which a detour through a zero-decimal currency would round
        # away. A fixed rule's amount is stored in the client's currency and is
        # re-read as the same number here -- "reserve 300" against a dollar
        # payment reserves 300 dollars. That is this feature's existing
        # behaviour; whether such an amount should be converted is a question
        # for capsule_funding_design.md, not something a routing wave changes.
        base_minor = amount_minor if amount_minor is not None else Money.from_major(
            str(max(0, amount or 0)), currency,
        ).minor
        for rule in rules:
            triggered = _triggered_legs(rule, description, entries, accounts)
            if not triggered:
                continue
            capsule = rule.capsule
            if not capsule:
                continue
            source_account_id = _resolve_rule_source_account_id(rule, entries, triggered[0])
            if source_account_id is None:
                continue
            reserved = _resolve_rule_amount_minor(rule, base_minor, currency=currency)
            if currency == client_currency:
                # The target, the claims and this reservation are all in the
                # same currency, so they can be subtracted from one another.
                posted_claim = claimed_minor(db, client_id, capsule.id).get(currency, 0)
                pending_claim = _pending_claimed_minor(db, client_id, capsule.id).get(currency, 0)
                headroom = (
                    (capsule.target_amount_minor or 0)
                    - posted_claim - pending_claim - evaluated_minor.get(capsule.id, 0)
                )
                reserved = min(reserved, max(0, headroom))
            # Otherwise there is no common unit: the capsule's target is
            # denominated in the client's currency and this reservation is not.
            # Reserving what the rule says is the only answer that invents
            # nothing -- converting would make the amount depend on a rate, and
            # subtracting cents from yen is the operation B5 removed. F3 reports
            # a capsule's claims in each currency so this stays visible.
            if reserved <= 0:
                continue
            if rule.destination_account_id is not None:
                destinations = [(rule.destination_account_id, Money(reserved, currency))]
            elif capsule.funding_sources:
                sources = sorted(capsule.funding_sources, key=lambda s: (s.sort_order, s.id))
                weights = [source.target_amount_minor for source in sources]
                if not any(weights):
                    continue
                # Fixed plan weights determine the routing shares.
                destinations = [(source.account_id, part) for source, part in zip(
                    sources, Money(reserved, currency).allocate(weights),
                )]
            else:
                continue
            for destination_account_id, part in destinations:
                if part.minor == 0 or source_account_id == destination_account_id:
                    continue
                specs.append(CapsuleTransferSpec(
                    capsule_id=capsule.id,
                    rule_id=rule.id,
                    capsule_name=capsule.name,
                    source_account_id=source_account_id,
                    destination_account_id=destination_account_id,
                    amount_minor=part.minor,
                    currency=currency,
                    auto_post=capsule.auto_post,
                ))
                if currency == client_currency:
                    # Only what the clamp can read is accumulated for it.
                    evaluated_minor[capsule.id] = (
                        evaluated_minor.get(capsule.id, 0) + part.minor
                    )
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
    # Re-evaluating a recorded trigger must return its own reservations rather
    # than clamp against them and create a second, smaller proposal. Amend first
    # withdraws the old reservations, so it still evaluates the new entry.
    existing = _reservation_query(db, transaction.client_id, transaction.id).all()
    if any(p.status != "rejected" for p in existing):
        if commit:
            db.commit()
        return [db.get(models.Transaction, p.posted_transaction_id)
                if p.status == "posted" and p.posted_transaction_id is not None else p
                for p in existing]
    specs = capsule_transfer_specs(
        db,
        transaction.client_id,
        entries=list(transaction.journal_entries),
        description=transaction.description,
        amount=transaction.amount,
        currency=transaction.currency,
        amount_minor=transaction.amount_minor,
    )
    resolved = []
    for spec in specs:
        amount_minor = spec.amount_minor
        legs = ledger_service.simple_legs(
            amount_minor, spec.source_account_id, spec.destination_account_id,
        )
        # Both automatic posting and later approval use these stored proposal legs.
        legs[0] = replace(legs[0], capsule_id=spec.capsule_id)
        columns = dict(
            date=transaction.date,
            description=f"Capsule reservation: {spec.capsule_name}",
            amount_minor=amount_minor,
            currency=transaction.currency,
            legs=legs,
        )
        # X3: an auto-posted reservation records a proposal too. The proposal is
        # the only thing that says which entry caused the transfer, and without
        # it an amended or deleted trigger could not find what it produced. The
        # auto-posting decision was made when the capsule was configured, so no
        # person decided at this moment and decided_by_client_id stays empty.
        proposal = ledger_service.propose_transaction(
            db,
            transaction.client_id,
            origin="capsule",
            origin_ref={"capsule_id": spec.capsule_id, "rule_id": spec.rule_id},
            trigger_transaction_id=transaction.id,
            **columns,
        )
        if not spec.auto_post:
            resolved.append(proposal)
        elif proposal.status == "pending":
            resolved.append(ledger_service.approve_proposal(
                db, proposal, actor_client_id=None,
            ))
        elif proposal.posted_transaction_id is not None:
            # An identical reservation was already posted, so propose_transaction
            # returned that record instead of writing a second one.
            resolved.append(db.get(models.Transaction, proposal.posted_transaction_id))
        else:
            resolved.append(proposal)
    if resolved and commit:
        db.commit()
    return resolved


@dataclass(frozen=True)
class CapsuleReservation:
    """One thing a transaction's capsule rules produced, queued or posted."""

    proposal_id: int
    capsule_id: int | None
    capsule_name: str | None
    amount: float
    currency: str
    status: str
    posted_transaction_id: int | None


def _reservation_query(db: Session, client_id: int, transaction_id: int):
    return db.query(models.TransactionProposal).filter(
        models.TransactionProposal.client_id == client_id,
        models.TransactionProposal.origin == "capsule",
        models.TransactionProposal.trigger_transaction_id == transaction_id,
    ).order_by(models.TransactionProposal.id)


def _as_reservation(db: Session, proposal: models.TransactionProposal) -> CapsuleReservation:
    capsule_id = (proposal.origin_ref or {}).get("capsule_id")
    capsule = db.get(models.Capsule, capsule_id) if capsule_id is not None else None
    return CapsuleReservation(
        proposal_id=proposal.id,
        capsule_id=capsule_id,
        capsule_name=capsule.name if capsule is not None else None,
        amount=proposal.amount,
        currency=proposal.currency,
        status=proposal.status,
        posted_transaction_id=proposal.posted_transaction_id,
    )


def capsule_reservations_for_transaction(
    db: Session, client_id: int, transaction_id: int,
) -> list[CapsuleReservation]:
    """What this transaction's capsule rules produced. A read; it writes nothing.

    Both kinds appear. A queued reservation is a pending proposal waiting for a
    decision; a posted one is a proposal carrying the transaction it became.
    """
    return [_as_reservation(db, proposal)
            for proposal in _reservation_query(db, client_id, transaction_id).all()]


def retract_capsule_reservations(
    db: Session, client_id: int, transaction_id: int, *, commit: bool = False,
) -> list[CapsuleReservation]:
    """Undo what a transaction's capsule rules produced, because its cause changed.

    X3: amending or deleting a trigger used to leave its reservations standing
    at the old figure, because only the posting path ever evaluated the rules.
    A reservation exists because of one entry, so when that entry stops saying
    what it said, the reservation has lost its basis and is removed.

    A pending proposal is withdrawn. A posted one takes its transaction with it,
    which moves money back out of the earmarked account -- the caller is the one
    that has to have told the user. A rejected proposal is left where it is:
    that was a person's decision about something that already happened, and the
    foreign key clears its trigger without destroying the record of it.
    """
    retracted = []
    for proposal in _reservation_query(db, client_id, transaction_id).all():
        if proposal.status == "rejected":
            continue
        retracted.append(_as_reservation(db, proposal))
        posted = (db.get(models.Transaction, proposal.posted_transaction_id)
                  if proposal.posted_transaction_id is not None else None)
        db.delete(proposal)
        if posted is not None:
            ledger_service.delete_transaction(db, posted)
    if retracted:
        invalidate_client(client_id)
    # The flush matters even when the caller commits: re-applying the rules
    # right after this would otherwise collide with the withdrawn proposal's
    # idempotency key, which does not depend on the fields an amend changes.
    if commit:
        db.commit()
    else:
        db.flush()
    return retracted


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
    base = Money.from_major(str(max(0, amount or 0)), currency)
    return Money(_resolve_rule_amount_minor(rule, base.minor, currency=currency), currency).to_float()


def _resolve_rule_amount_minor(rule: models.CapsuleRule, amount_minor: int, *, currency: str) -> int:
    if rule.amount_type == "percentage":
        ratio = Fraction(max(0, rule.percentage_bp or 0), 10000)
        return Money(max(0, amount_minor), currency).scale(ratio, rounding=ROUND_HALF_UP).minor
    # A fixed rule amount is stored in the client's currency, while the
    # reservation it produces is denominated in the triggering transaction's.
    # Nothing converts between the two: the figure is re-read as the same
    # number in the transaction's currency, which is what this has always
    # done -- "reserve 300" against a USD payment reserves 300 USD. Returning
    # rule.amount_minor directly would instead reserve 3.00 USD for a JPY
    # client, because the stored integer counts the client's minor units.
    # Whether a rule's amount should be converted is a question for
    # capsule_funding_design.md, not something to change in a routing wave.
    return Money.from_major(str(max(0.0, rule.amount_value or 0.0)), currency).minor
