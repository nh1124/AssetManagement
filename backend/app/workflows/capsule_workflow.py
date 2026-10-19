from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..domain.errors import Invalid, NotFound
from ..domain.journal import Leg
from ..domain.money import Money
from ..services import capsule_service, ledger_service
from ..services.cache_service import invalidate_client
from ..services.fx_service import get_client_currency


def set_account_claim(
    db: Session, client_id: int, capsule_id: int, *, account_id: int,
    target_amount: float, commit: bool = True,
) -> dict:
    currency = get_client_currency(db, client_id)
    try:
        raw_target = Decimal(str(target_amount))
        if not raw_target.is_finite() or raw_target < 0:
            raise ValueError
        target = Money.from_major(raw_target, currency)
    except (ValueError, ArithmeticError) as exc:
        raise Invalid("確保額は0以上の有限の金額を指定してください") from exc

    # Account first matches reconciliation's lock order and serializes setters
    # for different capsules sharing the same balance.
    account = ledger_service.get_account(db, client_id, account_id, for_update=True)
    if account is None:
        raise NotFound("口座が見つかりません")
    if account.account_type != "asset":
        raise Invalid("資産口座を指定してください")
    capsule = capsule_service.get_capsule(db, client_id, capsule_id, for_update=True)
    if capsule is None:
        raise NotFound("取り置きが見つかりません")
    if not any(source.account_id == account_id for source in capsule.funding_sources):
        raise Invalid("この口座は取り置きの資金源に紐づいていません")

    balances = ledger_service.account_balances_minor(db, client_id, account_id)
    claims = capsule_service.claimed_minor(db, client_id, capsule_id, account_id)
    # Capsules use client currency; accounts have journal denominations rather
    # than a fixed currency field. Foreign or mixed holdings need an explicit
    # currency decision, never an inferred exchange rate.
    if any(code != currency for code in balances.keys() | claims.keys()):
        raise Invalid("取り置きと口座の通貨が異なるため確保額を調整できません")
    current = claims.get(currency, 0)
    difference = target.minor - current
    if difference == 0:
        return {"status": "unchanged", "claimed": target.to_float(), "difference": 0.0}

    balance = balances.get(currency, 0)
    total_claim = capsule_service.account_claimed_minor(db, client_id, account_id).get(currency, 0)
    if target.minor > balance or total_claim + difference > balance:
        raise Invalid("確保額の合計が口座残高を超えています")

    amount = abs(difference)
    try:
        # Both legs stay on this account: this corrects attribution, never
        # transfers money, so the account's own balance cannot change.
        ledger_service.create_transaction(
            db, client_id=client_id, date=date.today(), currency=currency,
            description=f"確保額の調整: {capsule.name}", amount_minor=amount,
            legs=[Leg(account_id, debit=amount if difference > 0 else 0,
                      credit=amount if difference < 0 else 0, capsule_id=capsule_id),
                  Leg(account_id, debit=amount if difference < 0 else 0,
                      credit=amount if difference > 0 else 0)],
        )
        db.flush()
        if commit:
            db.commit()
            invalidate_client(client_id)
    except Exception:
        db.rollback()
        raise
    return {"status": "ok", "claimed": target.to_float(),
            "difference": Money(difference, currency).to_float()}


def contribute(
    db: Session, client_id: int, capsule_id: int, *, amount: float,
    from_account_id: int, commit: bool = True,
) -> dict:
    capsule = capsule_service.get_capsule(db, client_id, capsule_id)
    if not capsule:
        raise NotFound("Capsule not found")
    from_account = ledger_service.get_account(db, client_id, from_account_id)
    if not from_account:
        raise NotFound("Source account not found")
    if amount <= 0:
        raise Invalid("Contribution amount must be positive")

    sources = capsule_service.list_funding_sources(db, client_id, capsule.id)
    if not sources:
        raise NotFound("Reservation account not found")
    for source in sources:
        if not ledger_service.get_account(db, client_id, source.account_id):
            raise NotFound("Reservation account not found")
    remaining = capsule_service.remaining_target(db, capsule)
    if remaining <= 0:
        return {
            "status": "skipped",
            "message": "Capsule target already reached",
            "amount": 0.0,
            "new_balance": capsule_service.capsule_balance(db, capsule),
        }
    amount = min(amount, remaining)
    currency = get_client_currency(db, client_id)
    money = Money.from_major(str(amount), currency)
    weights = [source.target_amount_minor for source in sources]
    parts = money.allocate(weights if any(weights) else [1] * len(sources))
    ledger_service.create_transaction(
        db, client_id=client_id, date=date.today(),
        description=f"Manual contribution: {capsule.name}",
        amount_minor=money.minor, currency=currency,
        legs=[Leg(source.account_id, debit=part.minor, capsule_id=capsule.id)
              for source, part in zip(sources, parts) if part.minor]
             + [Leg(from_account.id, credit=money.minor)],
    )
    db.flush()
    if commit:
        db.commit()
        invalidate_client(client_id)
    return {
        "status": "ok",
        "amount": amount,
        "new_balance": capsule_service.capsule_balance(db, capsule),
    }

