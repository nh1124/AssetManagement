from dataclasses import FrozenInstanceError
from decimal import (
    Decimal, ROUND_05UP, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR,
    ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, localcontext,
)
from fractions import Fraction
from itertools import product
import operator

import pytest

from app.domain.money import Money


def test_allocate_conserves_every_unit_over_generated_amounts_and_weights():
    weights = [list(values) for length in range(1, 5)
               for values in product(range(4), repeat=length) if any(values)]
    weights += [[1, 7, 13], [0, 1, 1000, 0], [999, 1], [17]]
    for currency in ("JPY", "USD", "EUR"):
        for minor in range(-101, 102):
            original = Money(minor, currency)
            for values in weights:
                parts = original.allocate(values)
                assert sum(parts) == original
                assert len(parts) == len(values)
                for weight, part in zip(values, parts):
                    if weight == 0:
                        assert part.minor == 0
                    assert abs(part.minor) in {
                        abs(minor) * weight // sum(values),
                        -(-abs(minor) * weight // sum(values)),
                    }
                    assert part.minor * minor >= 0


@pytest.mark.parametrize("minor,weights,expected", [
    (100, [1, 1, 1], [34, 33, 33]),
    (1, [1, 1, 1], [1, 0, 0]),
    (-100, [1, 1, 1], [-34, -33, -33]),
    (2, [1, 2, 3], [0, 1, 1]),
    (1, [0, 1, 1], [0, 1, 0]),
    (0, [1, 0, 1], [0, 0, 0]),
])
def test_allocate_largest_remainders_then_input_order(minor, weights, expected):
    assert [part.minor for part in Money(minor, "JPY").allocate(weights)] == expected


@pytest.mark.parametrize("weights,error", [
    ([], ValueError), ([0, 0], ValueError), ([1, -1], ValueError),
    ([1, 0.5], TypeError), ([True], TypeError),
])
def test_allocate_rejects_undefined_or_noninteger_weights(weights, error):
    with pytest.raises(error):
        Money(100, "JPY").allocate(weights)


def test_arithmetic_ordering_and_sum_in_one_currency():
    small, large = Money(1, "USD"), Money(2, "USD")
    assert small + large == Money(3, "USD")
    assert small - large == -small
    assert 3 * small == small * 3 == Money(3, "USD")
    assert small < large and small <= small and large > small and large >= large
    assert small != large and Money(1, "USD") == small
    assert sum([small, large]) == Money(3, "USD")
    assert hash(small) == hash(Money(1, "USD"))
    with pytest.raises(FrozenInstanceError):
        small.minor = 2


@pytest.mark.parametrize("operation", [
    operator.add, operator.sub,
    operator.lt, operator.le, operator.gt, operator.ge,
])
def test_arithmetic_and_ordering_refuse_currency_mismatch(operation):
    # A mixed-currency sum or comparison would answer with a plausible number.
    with pytest.raises(ValueError, match="Currency mismatch: JPY vs USD"):
        operation(Money(100, "JPY"), Money(100, "USD"))


def test_equality_answers_across_currencies_instead_of_raising():
    # __eq__ must be safe to call from a container, so it answers False.
    assert Money(100, "JPY") != Money(100, "USD")
    assert not Money(100, "JPY") == Money(100, "USD")
    assert Money(100, "JPY") not in [Money(100, "USD")]
    assert len({Money(100, "JPY"), Money(100, "USD")}) == 2


@pytest.mark.parametrize("currency", ["JPY", "USD"])
@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("ratio", [Fraction(1, 2), Decimal("0.5")])
def test_scale_half_up_ties_away_from_zero_in_minor_units(currency, sign, ratio):
    money = Money(3 * sign, currency)
    assert money.scale(ratio, rounding=ROUND_HALF_UP) == Money(2 * sign, currency)
    assert money.scale(ratio) == Money(2 * sign, currency)
    assert money.scale(ratio, rounding=ROUND_HALF_DOWN) == Money(sign, currency)
    assert money.scale(ratio, rounding=ROUND_HALF_EVEN) == Money(2 * sign, currency)
    assert Money(sign, currency).scale(ratio, rounding=ROUND_HALF_EVEN) == Money(0, currency)


@pytest.mark.parametrize("rounding", [
    ROUND_05UP, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR,
    ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP,
])
def test_scale_matches_decimal_rounding_modes(rounding):
    for numerator in range(-120, 121):
        ratio = Fraction(numerator, 10)
        expected = int(Decimal(numerator).scaleb(-1).to_integral_value(rounding=rounding))
        assert Money(1, "JPY").scale(ratio, rounding=rounding).minor == expected


@pytest.mark.parametrize("currency,value,expected", [
    ("JPY", "123", "123"), ("USD", "46.48", "46.48"), ("EUR", "1050.95", "1050.95"),
    ("JPY", "1.5", "2"), ("JPY", "-1.5", "-2"),
    ("USD", "1.005", "1.01"), ("EUR", "-1.005", "-1.01"),
])
def test_major_round_trip_removes_fractional_minor_units(currency, value, expected):
    money = Money.from_major(value, currency)
    assert money.to_major() == Decimal(expected)
    assert Money.from_major(money.to_major(), currency) == money


def test_conversion_and_scaling_do_not_depend_on_decimal_context_precision():
    minor = 10 ** 50 + 1
    with localcontext() as context:
        context.prec = 2
        money = Money(minor, "USD")
        assert Money.from_major(money.to_major(), "USD") == money
        assert money.scale(Fraction(1, 2)).minor == (minor + 1) // 2


def test_float_boundaries_are_named_and_round_explicitly():
    assert Money.from_float(1.005, "USD", rounding=ROUND_HALF_UP) == Money(101, "USD")
    assert Money.from_float(1.005, "USD", rounding=ROUND_DOWN) == Money(100, "USD")
    assert repr(Money(101, "USD").to_float()) == "1.01"
    with pytest.raises(TypeError):
        float(Money(101, "USD"))


def test_float_and_boolean_values_cannot_enter_exact_arithmetic():
    with pytest.raises(TypeError, match="plain integer"):
        Money(1.0, "JPY")
    with pytest.raises(TypeError, match="plain integer"):
        Money(True, "JPY")
    with pytest.raises(TypeError, match="plain integer"):
        Money(1, "JPY") * 0.5
    with pytest.raises(TypeError, match="plain integer"):
        Money(1, "JPY") * True
    with pytest.raises(TypeError, match="Fraction or Decimal"):
        Money(1, "JPY").scale(0.5)
    with pytest.raises(TypeError, match="Decimal or str"):
        Money.from_major(1.0, "JPY")
    with pytest.raises(TypeError, match="requires a float"):
        Money.from_float(1, "JPY")
    with pytest.raises(ValueError, match="rounding mode"):
        Money(1, "JPY").scale(Fraction(1, 2), rounding="typo")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_values_are_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        Money.from_major(value, "JPY")
    with pytest.raises(ValueError, match="finite"):
        Money.from_float(float(value), "JPY")
    with pytest.raises(ValueError, match="finite"):
        Money(1, "JPY").scale(Decimal(value))


@pytest.mark.parametrize("currency", ["GBP", "US D", "jpy"])
def test_unknown_currency_requires_an_explicit_precision_decision(currency):
    with pytest.raises(ValueError, match="Unsupported currency.*minor-unit precision"):
        Money(100, currency)
    with pytest.raises(ValueError, match="Unsupported currency.*minor-unit precision"):
        Money.from_major("1.00", currency)
