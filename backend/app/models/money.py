from sqlalchemy import BigInteger, Float, Integer, case, cast, select, func
from sqlalchemy.types import TypeDecorator

from ..domain.money import CURRENCY_EXPONENTS, Money, normalize_currency


class MinorUnits(TypeDecorator):
    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # SQLite's BIGINT affinity alone would allow fractional stored money.
        if value is None:
            return None
        if type(value) is not int:
            raise TypeError("minor units must be a plain integer")
        return value


def major_expression(minor, currency):
    # Casting first avoids integer division on either supported database.
    return cast(minor, Float) / case(
        {code: 10 ** places for code, places in CURRENCY_EXPONENTS.items()},
        value=currency,
    )


class BasisPoints(MinorUnits):
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        value = super().process_bind_param(value, dialect)
        if value is not None and not -(2 ** 31) <= value < 2 ** 31:
            raise ValueError("basis points must fit a signed INTEGER")
        return value


def client_currency(row):
    if hasattr(row, "_deleted_money_currency"):
        return row._deleted_money_currency
    if row.__tablename__ == "capsule_holdings":
        client = row.capsule.client if row.capsule is not None else None
    else:
        client = row.client
    if client is None:
        raise ValueError(f"Cannot resolve client currency for {row.__tablename__}, row {row.id}")
    return settings_currency(client.general_settings)


def settings_currency(settings):
    # Cur1 allows an unset preference on a known client; an absent owner is different.
    value = settings.get("currency") if isinstance(settings, dict) else None
    return normalize_currency(value)


def client_currency_expression(cls):
    from .client import Client
    raw = func.upper(func.trim(Client.general_settings["currency"].as_string()))
    currency = func.coalesce(func.nullif(raw, ""), "JPY")
    if cls.__tablename__ == "capsule_holdings":
        from .capsule import Capsule
        return select(currency).select_from(Client).join(
            Capsule, Capsule.client_id == Client.id,
        ).where(Capsule.id == cls.capsule_id).correlate_except(Client, Capsule).scalar_subquery()
    return select(currency).where(Client.id == cls.client_id).correlate_except(Client).scalar_subquery()


def client_minor_default(major):
    def default(context):
        from .client import Client
        client_id = context.get_current_parameters().get("client_id")
        row = context.connection.execute(select(Client.general_settings).where(Client.id == client_id)).first()
        if row is None:
            raise ValueError(f"Cannot resolve client currency for client {client_id}")
        return Money.from_major(str(major), settings_currency(row[0])).minor
    return default
