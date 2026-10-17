"""Read account shelters and access assumptions without changing the journal."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import TypedDict

from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from .fx_service import get_client_currency
from .ledger_valuation import calculate_account_balances

UNTAXED_INSTITUTIONS = frozenset({"nisa_tsumitate", "nisa_growth", "ideco", "dc_corporate"})


class ShelterRow(TypedDict):
    institution: str
    currency: str
    balance: float
    taxed: bool


class LockedAccountRow(TypedDict):
    account_id: int
    name: str
    withdrawable_from_age: int
    available_on: str
    balances_minor: dict[str, int]


def _assets(db: Session, client_id: int) -> list[models.Account]:
    # Inactive holdings still belong to the person; hierarchy rollups would count them twice.
    return db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset",
    ).order_by(models.Account.id).all()


def blended_after_tax_return(
    db: Session, client_id: int, *, gross_annual_return: float, tax_rate: float,
    account_returns: dict[int, float] | None = None,
) -> float:
    """Rates use percent units, like the projection settings they replace."""
    accounts = _assets(db, client_id)
    currency = get_client_currency(db, client_id)
    balances = calculate_account_balances(db, accounts)
    weighted = total = 0.0
    for account in accounts:
        # A scalar projection is denominated in the client currency. Do not add
        # foreign units or silently treat a missing FX quote as equal value.
        balance = Money(balances[account.id].balances_minor.get(currency, 0), currency).to_float()
        if balance == 0:
            continue
        rate = (account_returns or {}).get(account.id, account.expected_return)
        if rate is None:
            rate = gross_annual_return
        tax = 0.0 if account.institution in UNTAXED_INSTITUTIONS else tax_rate / 100.0
        weighted += balance * rate * (1 - tax)
        total += balance
    # This is a blend, not a per-account simulation: a better estimate of the
    # same kind as the single rate it replaces, but still only one number.
    # Without holdings the future contributions have no known shelter.
    return weighted / total if total != 0 else gross_annual_return * (1 - tax_rate / 100.0)


def shelter_breakdown(db: Session, client_id: int) -> list[ShelterRow]:
    accounts = _assets(db, client_id)
    balances = calculate_account_balances(db, accounts)
    grouped: dict[tuple[str, str], int] = defaultdict(int)
    for account in accounts:
        for currency, minor in balances[account.id].balances_minor.items():
            grouped[(account.institution, currency)] += minor
    return [ShelterRow(institution=institution, currency=currency,
                       balance=Money(minor, currency).to_float(),
                       taxed=institution not in UNTAXED_INSTITUTIONS)
            for (institution, currency), minor in sorted(grouped.items())]


def locked_accounts(
    db: Session, client_id: int, *, as_of: date | None = None,
) -> list[LockedAccountRow]:
    evaluation_date = as_of or date.today()
    members = db.query(models.HouseholdMember).filter(
        models.HouseholdMember.client_id == client_id,
    ).order_by(models.HouseholdMember.birth_date, models.HouseholdMember.id).all()
    if not members:
        return []
    person = next((member for member in members if (member.relation or "").strip() == "本人"), members[0])
    accounts = _assets(db, client_id)
    balances = calculate_account_balances(db, accounts, as_of_date=evaluation_date)
    rows: list[LockedAccountRow] = []
    for account in accounts:
        age = account.withdrawable_from_age
        if age is None:
            continue
        try:
            available_on = person.birth_date.replace(year=person.birth_date.year + age)
        except ValueError:
            # Match V2: a leap-day birthday is reached on March 1 in a non-leap year.
            available_on = date(person.birth_date.year + age, 3, 1)
        if evaluation_date >= available_on:
            continue
        held = {currency: minor for currency, minor in balances[account.id].balances_minor.items() if minor > 0}
        if held:
            rows.append(LockedAccountRow(account_id=account.id, name=account.name,
                                         withdrawable_from_age=age, available_on=available_on.isoformat(),
                                         balances_minor=held))
    return rows


def locked_until_age_minor(rows: list[LockedAccountRow]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        for currency, minor in row["balances_minor"].items():
            totals[currency] += minor
    return dict(totals)
