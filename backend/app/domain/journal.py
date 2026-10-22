"""Pure journal rules shared by posting and ledger reads."""
from __future__ import annotations

from dataclasses import dataclass
from .messages import Message
from .money import Money


DEBIT_NORMAL_TYPES = {"asset", "expense"}
# This compares integer journal legs, not the float account cache retained until B5.
BALANCE_TOLERANCE = 0


@dataclass(frozen=True)
class Leg:
    """One side of an entry, as given to the posting code."""

    account_id: int
    debit: int = 0
    credit: int = 0
    memo: str | None = None
    capsule_id: int | None = None

    def __post_init__(self) -> None:
        if type(self.debit) is not int or type(self.credit) is not int:
            raise TypeError("Journal legs must contain integer minor units")


def coerce_leg(leg, currency: str) -> Leg:
    """Accept a Leg, a pydantic model or a plain mapping."""
    # Schemas and mappings carry major units; a domain Leg has already crossed this boundary.
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
            "capsule_id": getattr(leg, "capsule_id", None),
        }
    return Leg(
        account_id=data.get("account_id"),
        debit=Money.from_major(str(data.get("debit") or 0), currency).minor,
        credit=Money.from_major(str(data.get("credit") or 0), currency).minor,
        memo=data.get("memo"),
        capsule_id=data.get("capsule_id"),
    )


def validate_legs(legs: list[Leg], amount: int) -> None:
    """The ledger invariant, in one place.

    Two or more legs, each on exactly one side, and both sides summing to the
    transaction amount. The amount is a denormalisation of the legs, so it
    doubles as the checksum: a receipt total that disagrees with its breakdown
    is a mistake, not a rounding difference.
    """
    if type(amount) is not int:
        raise TypeError("Transaction amount must contain integer minor units")
    if len(legs) < 2:
        raise ValueError(Message("A journal entry needs at least two legs", ja="仕訳には2行以上が必要です。"))

    for leg in legs:
        if not leg.account_id:
            raise ValueError(Message("Every journal leg needs an account", ja="仕訳のすべての行に口座・科目を選んでください。"))
        if leg.debit < 0 or leg.credit < 0:
            raise ValueError(Message("Journal legs cannot be negative", ja="仕訳の金額は0以上にしてください。"))
        if (leg.debit > 0) == (leg.credit > 0):
            raise ValueError(Message(
                "A journal leg is either a debit or a credit, not both or neither",
                ja="仕訳の各行には借方か貸方のどちらか一方だけを入力してください。",
            ))

    total_debit = sum(leg.debit for leg in legs)
    total_credit = sum(leg.credit for leg in legs)
    if abs(total_debit - total_credit) > BALANCE_TOLERANCE:
        raise ValueError(Message(
            f"Journal entry does not balance: debit {total_debit} vs credit {total_credit}",
            ja=f"借方と貸方の合計が一致しません（借方 {total_debit}、貸方 {total_credit}）。",
        ))
    if abs(total_debit - amount) > BALANCE_TOLERANCE:
        raise ValueError(Message(
            f"Journal entry total {total_debit} does not match the transaction amount {amount}",
            ja=f"仕訳の合計 {total_debit} が取引の金額 {amount} と一致しません。",
        ))


def simple_legs(
    amount: int,
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
    total = amount
    return [
        Leg(account_id=to_account_id, debit=total),
        Leg(account_id=from_account_id, credit=total),
    ]


def signed_delta(account_type: str, *, debit: float, credit: float) -> float:
    if account_type in DEBIT_NORMAL_TYPES:
        return debit - credit
    return credit - debit
