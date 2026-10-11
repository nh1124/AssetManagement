"""Pure journal rules shared by posting and ledger reads."""
from __future__ import annotations

from dataclasses import dataclass


DEBIT_NORMAL_TYPES = {"asset", "expense", "item"}
BALANCE_TOLERANCE = 0.01


@dataclass(frozen=True)
class Leg:
    """One side of an entry, as given to the posting code."""

    account_id: int
    debit: float = 0.0
    credit: float = 0.0
    memo: str | None = None


def coerce_leg(leg) -> Leg:
    """Accept a Leg, a pydantic model or a plain mapping."""
    if isinstance(leg, Leg):
        return leg
    if isinstance(leg, dict):
        data = leg
    else:
        data = {
            "account_id": getattr(leg, "account_id", None),
            "debit": getattr(leg, "debit", 0.0),
            "credit": getattr(leg, "credit", 0.0),
            "memo": getattr(leg, "memo", None),
        }
    return Leg(
        account_id=data.get("account_id"),
        debit=float(data.get("debit") or 0.0),
        credit=float(data.get("credit") or 0.0),
        memo=data.get("memo"),
    )


def validate_legs(legs: list[Leg], amount: float) -> None:
    """The ledger invariant, in one place.

    Two or more legs, each on exactly one side, and both sides summing to the
    transaction amount. The amount is a denormalisation of the legs, so it
    doubles as the checksum: a receipt total that disagrees with its breakdown
    is a mistake, not a rounding difference.
    """
    if len(legs) < 2:
        raise ValueError("A journal entry needs at least two legs")

    for leg in legs:
        if not leg.account_id:
            raise ValueError("Every journal leg needs an account")
        if leg.debit < 0 or leg.credit < 0:
            raise ValueError("Journal legs cannot be negative")
        if (leg.debit > 0) == (leg.credit > 0):
            raise ValueError("A journal leg is either a debit or a credit, not both or neither")

    total_debit = sum(leg.debit for leg in legs)
    total_credit = sum(leg.credit for leg in legs)
    if abs(total_debit - total_credit) > BALANCE_TOLERANCE:
        raise ValueError(
            f"Journal entry does not balance: debit {total_debit} vs credit {total_credit}"
        )
    if abs(total_debit - (amount or 0.0)) > BALANCE_TOLERANCE:
        raise ValueError(
            f"Journal entry total {total_debit} does not match the transaction amount {amount}"
        )


def simple_legs(
    amount: float | None,
    from_account_id: int | None,
    to_account_id: int | None,
) -> list[Leg]:
    """The two legs a from/to pair describes.

    from_account is the credit side and to_account the debit side, which is the
    direction the API and the UI have always used. Both are required: there is
    nothing left to infer a missing account from, and inferring one is how
    transactions used to land on whichever account happened to come first.
    The accounts themselves are checked where every leg is.
    """
    if from_account_id is None or to_account_id is None:
        raise ValueError(
            "A transaction needs both from_account_id and to_account_id, or explicit legs"
        )
    total = amount or 0.0
    return [
        Leg(account_id=to_account_id, debit=total),
        Leg(account_id=from_account_id, credit=total),
    ]


def signed_delta(account_type: str, *, debit: float, credit: float) -> float:
    if account_type in DEBIT_NORMAL_TYPES:
        return debit - credit
    return credit - debit
