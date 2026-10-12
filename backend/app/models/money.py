from sqlalchemy import BigInteger, Float, case, cast
from sqlalchemy.types import TypeDecorator

from ..domain.money import CURRENCY_EXPONENTS


class MinorUnits(TypeDecorator):
    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # SQLite's BIGINT affinity alone would allow fractional ledger values.
        if type(value) is not int:
            raise TypeError("minor units must be a plain integer")
        return value


def major_expression(minor, currency):
    # Casting first avoids integer division on either supported database.
    return cast(minor, Float) / case(
        {code: 10 ** places for code, places in CURRENCY_EXPONENTS.items()},
        value=currency,
    )
