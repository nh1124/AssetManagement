from __future__ import annotations

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
    assert validate_legs([Leg(1, debit=100), Leg(2, credit=100)], 100) is None


@pytest.mark.parametrize(
    "legs, message",
    [
        pytest.param([], "A journal entry needs at least two legs", id="no-legs"),
        pytest.param([Leg(1, debit=100)], "A journal entry needs at least two legs", id="one-leg"),
        pytest.param(
            [Leg(None, debit=100), Leg(2, credit=100)],
            "Every journal leg needs an account", id="missing-account",
        ),
        pytest.param(
            [Leg(0, debit=100), Leg(2, credit=100)],
            "Every journal leg needs an account", id="zero-account",
        ),
        pytest.param(
            [Leg(1, debit=-100), Leg(2, credit=100)],
            "Journal legs cannot be negative", id="negative-debit",
        ),
        pytest.param(
            [Leg(1, debit=100), Leg(2, credit=-100)],
            "Journal legs cannot be negative", id="negative-credit",
        ),
        pytest.param(
            [Leg(1, debit=100, credit=100), Leg(2, credit=100)],
            "A journal leg is either a debit or a credit, not both or neither", id="both-sides",
        ),
        pytest.param(
            [Leg(1), Leg(2, credit=100)],
            "A journal leg is either a debit or a credit, not both or neither", id="neither-side",
        ),
    ],
)
def test_invalid_leg_shape_is_refused_with_its_current_message(legs, message):
    with pytest.raises(ValueError) as error:
        validate_legs(legs, 100)
    assert str(error.value) == message


def test_disagreeing_sides_are_refused():
    with pytest.raises(ValueError) as error:
        validate_legs([Leg(1, debit=100), Leg(2, credit=99)], 100)
    assert str(error.value) == "Journal entry does not balance: debit 100 vs credit 99"


def test_balanced_sides_that_disagree_with_the_amount_are_refused():
    with pytest.raises(ValueError) as error:
        validate_legs([Leg(1, debit=100), Leg(2, credit=100)], 99)
    assert str(error.value) == "Journal entry total 100 does not match the transaction amount 99"


@pytest.mark.parametrize("check", ["sides", "transaction-amount"])
def test_equal_integer_totals_are_accepted(check):
    assert BALANCE_TOLERANCE == 0
    assert validate_legs([Leg(1, debit=100), Leg(2, credit=100)], 100) is None


@pytest.mark.parametrize("check", ["sides", "transaction-amount"])
def test_difference_of_one_minor_unit_is_refused(check):
    credit = 101 if check == "sides" else 100
    amount = 100 if check == "sides" else 101
    with pytest.raises(ValueError):
        validate_legs([Leg(1, debit=100), Leg(2, credit=credit)], amount)


def test_simple_legs_debits_destination_and_credits_source():
    assert simple_legs(100, from_account_id=1, to_account_id=2) == [
        Leg(2, debit=100),
        Leg(1, credit=100),
    ]


@pytest.mark.parametrize(
    "from_account_id, to_account_id",
    [pytest.param(None, 2, id="missing-source"), pytest.param(1, None, id="missing-destination")],
)
def test_simple_legs_refuses_a_missing_account(from_account_id, to_account_id):
    with pytest.raises(ValueError) as error:
        simple_legs(100, from_account_id, to_account_id)
    assert str(error.value) == (
        "A transaction needs both from_account_id and to_account_id, or explicit legs"
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(SimpleNamespace(account_id=1, debit=100, credit=0), id="attribute-object"),
        pytest.param({"account_id": 1, "debit": 100, "credit": 0}, id="dict"),
        pytest.param(Leg(1, debit=100), id="existing-leg"),
    ],
)
def test_coerce_leg_accepts_current_input_forms(source):
    coerced = coerce_leg(source, "JPY")
    assert coerced == Leg(1, debit=100)
    if isinstance(source, Leg):
        assert coerced is source


@pytest.mark.parametrize(
    "account_type, debit, credit, expected",
    [
        pytest.param("asset", 100, 0, 100, id="debit-increases-assets"),
        pytest.param("asset", 0, 100, -100, id="credit-decreases-assets"),
        pytest.param("liability", 100, 0, -100, id="debit-decreases-liabilities"),
        pytest.param("liability", 0, 100, 100, id="credit-increases-liabilities"),
    ],
)
def test_signed_delta_follows_account_normal_side(account_type, debit, credit, expected):
    assert signed_delta(account_type, debit=debit, credit=credit) == expected
