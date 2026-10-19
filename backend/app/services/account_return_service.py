"""Blend scenario account yields over positive holdings in the client currency."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from .fx_service import get_client_currency
from .ledger_valuation import calculate_account_balances


def _positive_asset_balances(db: Session, client_id: int) -> list[tuple[models.Account, float]]:
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset",
    ).all()
    currency = get_client_currency(db, client_id)
    balances = calculate_account_balances(db, accounts)
    # Only positive active holdings in the projection currency earn a return.
    return [(account, Money(minor, currency).to_float()) for account in accounts
            if account.is_active and (minor := balances[account.id].balances_minor.get(currency, 0)) > 0]


def positive_asset_balance(db: Session, client_id: int) -> float:
    """Principal that can earn the client-currency blended return."""
    return sum(balance for _, balance in _positive_asset_balances(db, client_id))


def blended_return(
    db: Session, client_id: int, *, gross_annual_return: float, tax_rate: float,
    account_returns: dict[int, float] | None = None,
) -> float:
    """Rates use percent units, like the projection settings they replace."""
    weighted = total = 0.0
    # Signed weights let overdrafts invert rate changes when the total is
    # negative. Only money held can earn a return; debt has no blend weight.
    for account, balance in _positive_asset_balances(db, client_id):
        rate = (account_returns or {}).get(account.id, gross_annual_return)
        tax = tax_rate / 100.0
        weighted += balance * rate * (1 - tax)
        total += balance
    # Until WP15 this remains a single rate weighted over current holdings.
    return weighted / total if total != 0 else gross_annual_return * (1 - tax_rate / 100.0)


