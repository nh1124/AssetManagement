from __future__ import annotations

from math import inf, nextafter
from types import SimpleNamespace

import pytest

from app.domain.journal import (
    BALANCE_TOLERANCE,
    Leg,
    coerce_leg,
    signed_delta,
    simple_legs,
    validate_legs,
)


def test_balanced_two_leg_entry_validates():
    assert validate_legs([Leg(1, debit=100.0), Leg(2, credit=100.0)], 100.0) is None


@pytest.mark.parametrize(
    "legs, message",
    [
        pytest.param([], "A journal entry needs at least two legs", id="no-legs"),
        pytest.param([Leg(1, debit=100.0)], "A journal entry needs at least two legs", id="one-leg"),
        pytest.param(
            [Leg(None, debit=100.0), Leg(2, credit=100.0)],
            "Every journal leg needs an account", id="missing-account",
        ),
        pytest.param(
            [Leg(0, debit=100.0), Leg(2, credit=100.0)],
            "Every journal leg needs an account", id="zero-account",
        ),
        pytest.param(
            [Leg(1, debit=-100.0), Leg(2, credit=100.0)],
            "Journal legs cannot be negative", id="negative-debit",
        ),
        pytest.param(
            [Leg(1, debit=100.0), Leg(2, credit=-100.0)],
            "Journal legs cannot be negative", id="negative-credit",
        ),
        pytest.param(
            [Leg(1, debit=100.0, credit=100.0), Leg(2, credit=100.0)],
            "A journal leg is either a debit or a credit, not both or neither", id="both-sides",
        ),
        pytest.param(
            [Leg(1), Leg(2, credit=100.0)],
            "A journal leg is either a debit or a credit, not both or neither", id="neither-side",
        ),
    ],
)
def test_invalid_leg_shape_is_refused_with_its_current_message(legs, message):
    with pytest.raises(ValueError) as error:
        validate_legs(legs, 100.0)
    assert str(error.value) == message


def test_disagreeing_sides_are_refused():
    with pytest.raises(ValueError) as error:
        validate_legs([Leg(1, debit=100.0), Leg(2, credit=99.0)], 100.0)
    assert str(error.value) == "Journal entry does not balance: debit 100.0 vs credit 99.0"


def test_balanced_sides_that_disagree_with_the_amount_are_refused():
    with pytest.raises(ValueError) as error:
        validate_legs([Leg(1, debit=100.0), Leg(2, credit=100.0)], 99.0)
    assert str(error.value) == "Journal entry total 100.0 does not match the transaction amount 99.0"


@pytest.mark.parametrize("check", ["sides", "transaction-amount"])
def test_difference_exactly_at_tolerance_is_accepted(check):
    # Small totals make the subtraction exactly the stored float tolerance.
    total = BALANCE_TOLERANCE
    boundary = 2 * BALANCE_TOLERANCE
    assert abs(total - boundary) == BALANCE_TOLERANCE
    credit = boundary if check == "sides" else total
    amount = total if check == "sides" else boundary
    assert validate_legs([Leg(1, debit=total), Leg(2, credit=credit)], amount) is None


@pytest.mark.parametrize("check", ["sides", "transaction-amount"])
def test_difference_just_above_tolerance_is_refused(check):
    total = BALANCE_TOLERANCE
    above_boundary = nextafter(2 * BALANCE_TOLERANCE, inf)
    assert abs(total - above_boundary) > BALANCE_TOLERANCE
    credit = above_boundary if check == "sides" else total
    amount = total if check == "sides" else above_boundary
    with pytest.raises(ValueError) as error:
        validate_legs([Leg(1, debit=total), Leg(2, credit=credit)], amount)
    expected = (
        f"Journal entry does not balance: debit {total} vs credit {credit}"
        if check == "sides" else
        f"Journal entry total {total} does not match the transaction amount {amount}"
    )
    assert str(error.value) == expected


def test_simple_legs_debits_destination_and_credits_source():
    assert simple_legs(100.0, from_account_id=1, to_account_id=2) == [
        Leg(2, debit=100.0),
        Leg(1, credit=100.0),
    ]


@pytest.mark.parametrize(
    "from_account_id, to_account_id",
    [pytest.param(None, 2, id="missing-source"), pytest.param(1, None, id="missing-destination")],
)
def test_simple_legs_refuses_a_missing_account(from_account_id, to_account_id):
    with pytest.raises(ValueError) as error:
        simple_legs(100.0, from_account_id, to_account_id)
    assert str(error.value) == (
        "A transaction needs both from_account_id and to_account_id, or explicit legs"
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(SimpleNamespace(account_id=1, debit=100.0, credit=0.0), id="attribute-object"),
        pytest.param({"account_id": 1, "debit": 100.0, "credit": 0.0}, id="dict"),
        pytest.param(Leg(1, debit=100.0), id="existing-leg"),
    ],
)
def test_coerce_leg_accepts_current_input_forms(source):
    coerced = coerce_leg(source)
    assert coerced == Leg(1, debit=100.0)
    if isinstance(source, Leg):
        assert coerced is source


@pytest.mark.parametrize(
    "account_type, debit, credit, expected",
    [
        pytest.param("asset", 100.0, 0.0, 100.0, id="debit-increases-assets"),
        pytest.param("asset", 0.0, 100.0, -100.0, id="credit-decreases-assets"),
        pytest.param("liability", 100.0, 0.0, -100.0, id="debit-decreases-liabilities"),
        pytest.param("liability", 0.0, 100.0, 100.0, id="credit-increases-liabilities"),
    ],
)
def test_signed_delta_follows_account_normal_side(account_type, debit, credit, expected):
    assert signed_delta(account_type, debit=debit, credit=credit) == expected
