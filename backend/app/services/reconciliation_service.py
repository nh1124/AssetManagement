"""Compare a statement to journal facts and post its explicit correction."""
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, Invalid, NotFound
from ..domain.journal import Leg
from ..domain.money import Money
from .ledger_service import create_transaction, get_account
from .cache_service import invalidate_client
from .fx_service import get_client_currency


def statement_money(db: Session, client_id: int, statement: Decimal | str, currency: str | None = None) -> Money:
    try:
        return Money.from_major(str(statement), currency or get_client_currency(db, client_id))
    except (ValueError, ArithmeticError) as exc:
        raise Invalid("Statement balance must be finite and use a supported currency") from exc


def compare_to_statement(
    db: Session, client_id: int, account_id: int, *, as_of: date,
    statement_minor: int, currency: str | None = None,
) -> dict:
    account = get_account(db, client_id, account_id)
    if account is None:
        raise NotFound("Account not found for this client")
    currency = currency or get_client_currency(db, client_id)
    Money(statement_minor, currency)
    # A statement concerns a denomination, not an FX valuation. Debit-net
    # balances make a higher statement require a debit for every account type.
    query = db.query(models.JournalEntry).join(
        models.Transaction, models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(
        models.Transaction.client_id == client_id,
        models.Transaction.date <= as_of,
        models.Transaction.currency == currency,
        models.JournalEntry.account_id == account_id,
    )
    ledger_minor = int(query.with_entities(func.coalesce(func.sum(
        models.JournalEntry.debit_minor - models.JournalEntry.credit_minor,
    ), 0)).scalar())
    # Claims use the same cutoff and denomination as the balance. Funding
    # plans and pending proposals say nothing about money already attributed.
    rows = query.join(models.Capsule, models.Capsule.id == models.JournalEntry.capsule_id).filter(
        models.Capsule.client_id == client_id,
    ).with_entities(
        models.Capsule.id, models.Capsule.name,
        func.sum(models.JournalEntry.debit_minor - models.JournalEntry.credit_minor),
    ).group_by(models.Capsule.id, models.Capsule.name).order_by(models.Capsule.id).all()
    return {
        "account": {"id": account.id, "name": account.name, "account_type": account.account_type},
        "as_of": as_of, "ledger_minor": ledger_minor, "statement_minor": statement_minor,
        "difference_minor": statement_minor - ledger_minor, "currency": currency,
        "capsule_claims": [{"capsule_id": capsule_id, "capsule_name": name, "claimed_minor": int(claim)}
                           for capsule_id, name, claim in rows if claim],
    }


def post_adjustment(
    db: Session, client_id: int, account_id: int, *, as_of: date,
    statement_minor: int, counter_account_id: int, capsule_id: int | None = None,
    note: str | None = None, commit: bool = True, currency: str | None = None,
    expected_ledger_minor: int | None = None,
) -> models.Transaction:
    try:
        # Serialize simultaneous corrections of this account: a repeated
        # statement must see the first correction and refuse its zero delta.
        account = db.query(models.Account).filter(
            models.Account.client_id == client_id, models.Account.id == account_id,
        ).with_for_update().first()
        if account is None:
            raise NotFound("Account not found for this client")
        if counter_account_id == account_id:
            raise Invalid("Counter account must differ from the reconciled account")
        if get_account(db, client_id, counter_account_id) is None:
            raise NotFound("Counter account not found for this client")
        if capsule_id is not None and db.query(models.Capsule).filter(
            models.Capsule.client_id == client_id, models.Capsule.id == capsule_id,
        ).first() is None:
            raise NotFound("Capsule not found for this client")
        comparison = compare_to_statement(db, client_id, account_id, as_of=as_of,
                                          statement_minor=statement_minor, currency=currency)
        if expected_ledger_minor is not None and expected_ledger_minor != comparison["ledger_minor"]:
            raise Conflict("Ledger balance changed; compare the statement again before posting")
        difference = comparison["difference_minor"]
        if difference == 0:
            raise Invalid("Statement already matches the ledger; zero difference has nothing to post")
        amount = abs(difference)
        transaction = create_transaction(
            db, client_id=client_id, date=as_of, currency=comparison["currency"], amount_minor=amount,
            description=note or f"残高照合：{account.name}",
            legs=[Leg(account_id, debit=amount if difference > 0 else 0,
                      credit=amount if difference < 0 else 0, capsule_id=capsule_id),
                  Leg(counter_account_id, debit=amount if difference < 0 else 0,
                      credit=amount if difference > 0 else 0)],
        )
        # This is the exact correction requested. Triggering automatic reserve
        # transfers here could immediately move the reconciled balance again.
        if commit:
            db.commit()
            db.refresh(transaction)
            invalidate_client(client_id)
        else:
            db.flush()
        return transaction
    except Exception:
        db.rollback()
        raise
