"""Minor-unit money with exact allocation and explicit rounding boundaries."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import (
    Decimal, ROUND_05UP, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR,
    ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP,
)
from fractions import Fraction
from functools import total_ordering

from .messages import Message


CURRENCY_EXPONENTS = {"JPY": 0, "USD": 2, "EUR": 2}

DEFAULT_CURRENCY = "JPY"


def _places(currency: str) -> int:
    # A new currency needs an explicit precision decision; guessing hides typos.
    if currency not in CURRENCY_EXPONENTS:
        raise ValueError(Message(
            f"Unsupported currency {currency!r}; define its minor-unit precision",
            ja=f"{currency!r} は対応していない通貨です。",
        ))
    return CURRENCY_EXPONENTS[currency]


def normalize_currency(currency: str | None, *, default: str = DEFAULT_CURRENCY) -> str:
    """The canonical code for a currency, or the default when none was stated.

    Normalising and validating belong in one call. A caller that accepts
    " usd " has already decided to take whatever its input holds, so the only
    honest answer to a code this module cannot denominate is to refuse it
    here -- at the boundary that read it -- rather than pass it on to whichever
    Money happens to be built from it next.
    """
    code = (currency or "").strip().upper() or default
    _places(code)
    return code


def _round_minor(value: Fraction, rounding: str) -> int:
    # Integer remainders avoid Decimal context precision changing a half-way tie.
    whole, remainder = divmod(abs(value.numerator), value.denominator)
    sign = -1 if value < 0 else 1
    if rounding == ROUND_HALF_UP:
        up = 2 * remainder >= value.denominator
    elif rounding == ROUND_HALF_DOWN:
        up = 2 * remainder > value.denominator
    elif rounding == ROUND_HALF_EVEN:
        up = 2 * remainder > value.denominator or (
            2 * remainder == value.denominator and whole % 2 == 1
        )
    elif rounding == ROUND_UP:
        up = bool(remainder)
    elif rounding == ROUND_DOWN:
        up = False
    elif rounding == ROUND_CEILING:
        up = sign > 0 and bool(remainder)
    elif rounding == ROUND_FLOOR:
        up = sign < 0 and bool(remainder)
    elif rounding == ROUND_05UP:
        up = bool(remainder) and whole % 10 in (0, 5)
    else:
        raise ValueError(f"Unsupported rounding mode {rounding!r}")
    return sign * (whole + int(up))


@total_ordering
@dataclass(frozen=True, eq=False)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        if type(self.minor) is not int:
            raise TypeError("minor must be a plain integer")
        _places(self.currency)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.minor + other.minor, self.currency)

    def __radd__(self, other: Money | int) -> Money:
        # sum() starts with integer zero; it must not admit other bare amounts.
        if type(other) is int and other == 0:
            return self
        return self.__add__(other)

    def __sub__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.minor, self.currency)

    def __mul__(self, multiplier: int) -> Money:
        # Floats hide approximation and a rounding choice; use scale() instead.
        if type(multiplier) is not int:
            raise TypeError("Money multiplication requires a plain integer; use scale for ratios")
        return Money(self.minor * multiplier, self.currency)

    __rmul__ = __mul__

    def __eq__(self, other: object) -> bool:
        # Equality answers rather than refusing, because Python calls __eq__
        # from places the author cannot see: `in`, dict and set membership,
        # assertion diffing, logging a container. An exception from here
        # surfaces far from the comparison that caused it. Arithmetic and
        # ordering still refuse a mismatch, where a wrong answer would be a
        # plausible-looking number instead of a visible False.
        if not isinstance(other, Money):
            return NotImplemented
        return (self.minor, self.currency) == (other.minor, other.currency)

    def __lt__(self, other: Money) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency(other)
        return self.minor < other.minor

    def __hash__(self) -> int:
        return hash((self.minor, self.currency))

    def scale(self, ratio: Fraction | Decimal, *, rounding: str = ROUND_HALF_UP) -> Money:
        """Round to minor units; HALF_UP sends ties away from zero, as for yen."""
        if not isinstance(ratio, (Fraction, Decimal)):
            raise TypeError("ratio must be a Fraction or Decimal, never a float")
        if isinstance(ratio, Decimal) and not ratio.is_finite():
            raise ValueError("ratio must be finite")
        return Money(_round_minor(self.minor * Fraction(ratio), rounding), self.currency)

    def allocate(self, weights: Sequence[int]) -> list[Money]:
        """Largest remainders win; ties use input order. Negatives split magnitude."""
        weights = list(weights)
        if not weights:
            raise ValueError("weights must not be empty")
        if any(type(weight) is not int for weight in weights):
            raise TypeError("weights must be plain integers")
        if any(weight < 0 for weight in weights) or sum(weights) == 0:
            raise ValueError("weights must be nonnegative with a positive total")
        total = sum(weights)
        shares = [divmod(abs(self.minor) * weight, total) for weight in weights]
        parts = [whole for whole, _ in shares]
        remaining = abs(self.minor) - sum(parts)
        order = sorted(range(len(weights)), key=lambda index: (-shares[index][1], index))
        for index in order[:remaining]:
            parts[index] += 1
        sign = -1 if self.minor < 0 else 1
        return [Money(sign * part, self.currency) for part in parts]

    @classmethod
    def from_major(
        cls, value: Decimal | str, currency: str, *, rounding: str = ROUND_HALF_UP,
    ) -> Money:
        """Human amounts round HALF_UP by default; fractional minor units cannot persist."""
        if not isinstance(value, (Decimal, str)):
            raise TypeError("major amount must be a Decimal or str; use from_float at float boundaries")
        major = Decimal(value)
        if not major.is_finite():
            raise ValueError("major amount must be finite")
        return cls(_round_minor(Fraction(major) * 10 ** _places(currency), rounding), currency)

    def to_major(self) -> Decimal:
        # Constructing a Decimal tuple preserves large integers under any context.
        sign, digits, _ = Decimal(self.minor).as_tuple()
        return Decimal((sign, digits, -_places(self.currency)))

    @classmethod
    def from_float(
        cls, value: float, currency: str, *, rounding: str = ROUND_HALF_UP,
    ) -> Money:
        """Legacy float boundary, not a convenience; round its decimal repr HALF_UP by default."""
        if type(value) is not float:
            raise TypeError("from_float requires a float")
        return cls.from_major(str(value), currency, rounding=rounding)

    def to_float(self) -> float:
        """Explicit boundary back to legacy float columns and APIs."""
        return float(self.to_major())
