"""Retire the account balance cache and store account settings in minor units."""
from decimal import Decimal
import logging

from alembic import op
import sqlalchemy as sa

from app.domain.journal import DEBIT_NORMAL_TYPES
from app.domain.money import CURRENCY_EXPONENTS

revision = "20261012_0053"
down_revision = "20261012_0052"
branch_labels = None
depends_on = None

MONEY_COLUMNS = ("role_target_amount", "liability_minimum_payment", "liability_fixed_payment_amount")


def _tables():
    metadata = sa.MetaData()
    return {name: sa.Table(name, metadata, autoload_with=op.get_bind())
            for name in ("accounts", "clients", "journal_entries", "transactions")}


def _currency(accounts, clients):
    # Old settings cannot be denominated by guessing an unset client preference.
    currency = sa.func.upper(sa.func.trim(clients.c.general_settings["currency"].as_string()))
    return sa.select(currency).where(clients.c.id == accounts.c.client_id).correlate_except(clients).scalar_subquery()


def _has_money(accounts, minor=False):
    suffix = "_minor" if minor else ""
    return sa.or_(*(accounts.c[f"{name}{suffix}"].is_not(None) for name in MONEY_COLUMNS))


def _verify_currency(connection, accounts, currency, minor=False):
    # A row with no money has no denomination to get wrong; requiring one
    # would block migration over data that does not exist.
    invalid = connection.execute(sa.select(accounts.c.id, currency).where(
        _has_money(accounts, minor),
        sa.or_(currency.is_(None), currency.not_in(CURRENCY_EXPONENTS)),
    )).first()
    if invalid:
        raise ValueError(f"Cannot resolve supported currency in accounts, row {invalid[0]}: {invalid[1]!r}")


def upgrade():
    connection = op.get_bind()
    tables = _tables()
    accounts = tables["accounts"]
    currency = _currency(accounts, tables["clients"])
    _verify_currency(connection, accounts, currency)
    nullable = {name: accounts.c[name].nullable for name in MONEY_COLUMNS}
    for name in MONEY_COLUMNS:
        if accounts.c[name].server_default is not None:
            raise ValueError(f"Unexpected money server default in accounts.{name}")
    # Validate before DDL so sub-unit amounts cannot silently disappear.
    for row in connection.execute(sa.select(accounts.c.id, currency, *(accounts.c[name] for name in MONEY_COLUMNS)).where(
        _has_money(accounts),
    )):
        for name, value in zip(MONEY_COLUMNS, row[2:]):
            if value is None:
                continue
            minor = Decimal(str(value)) * 10 ** CURRENCY_EXPONENTS[row[1]]
            if not minor.is_finite() or minor != minor.to_integral_value():
                raise ValueError(f"Lossy conversion in accounts.{name}, row {row[0]}")
            if not -(2 ** 63) <= minor < 2 ** 63:
                raise ValueError(f"Minor-unit overflow in accounts.{name}, row {row[0]}")
    for name in MONEY_COLUMNS:
        op.add_column("accounts", sa.Column(f"{name}_minor", sa.BigInteger(), nullable=True))
    tables = _tables()
    accounts = tables["accounts"]
    currency = _currency(accounts, tables["clients"])
    factor = sa.case({code: 10 ** places for code, places in CURRENCY_EXPONENTS.items()}, value=currency)
    connection.execute(accounts.update().where(_has_money(accounts)).values({
        f"{name}_minor": sa.cast(sa.func.round(accounts.c[name] * factor), sa.BigInteger())
        for name in MONEY_COLUMNS
    }))
    for row in connection.execute(sa.select(accounts.c.id, currency, *(
        column for name in MONEY_COLUMNS for column in (accounts.c[name], accounts.c[f"{name}_minor"])
    ))):
        for i, name in enumerate(MONEY_COLUMNS):
            old, new = row[2 + i * 2:4 + i * 2]
            if (old is None) != (new is None) or (
                old is not None and Decimal(str(old)) * 10 ** CURRENCY_EXPONENTS[row[1]] != new
            ):
                raise ValueError(f"Lossy conversion in accounts.{name}, row {row[0]}")
    with op.batch_alter_table("accounts") as batch:
        for name in MONEY_COLUMNS:
            batch.alter_column(f"{name}_minor", existing_type=sa.BigInteger(), nullable=nullable[name])
            batch.drop_column(name)
        batch.drop_column("balance")


def downgrade():
    connection = op.get_bind()
    tables = _tables()
    accounts = tables["accounts"]
    currency = _currency(accounts, tables["clients"])
    _verify_currency(connection, accounts, currency, minor=True)
    nullable = {name: accounts.c[f"{name}_minor"].nullable for name in MONEY_COLUMNS}
    for name in MONEY_COLUMNS:
        op.add_column("accounts", sa.Column(name, sa.Float(), nullable=True))
    op.add_column("accounts", sa.Column("balance", sa.Float(), nullable=True))
    tables = _tables()
    accounts = tables["accounts"]
    currency = _currency(accounts, tables["clients"])
    factor = sa.case({code: 10 ** places for code, places in CURRENCY_EXPONENTS.items()}, value=currency)
    connection.execute(accounts.update().where(_has_money(accounts, minor=True)).values({
        name: sa.cast(accounts.c[f"{name}_minor"], sa.Float()) / factor for name in MONEY_COLUMNS
    }))
    for row in connection.execute(sa.select(accounts.c.id, currency, *(
        column for name in MONEY_COLUMNS for column in (accounts.c[name], accounts.c[f"{name}_minor"])
    ))):
        for i, name in enumerate(MONEY_COLUMNS):
            major, minor = row[2 + i * 2:4 + i * 2]
            if minor is not None and Decimal(str(major)) * 10 ** CURRENCY_EXPONENTS[row[1]] != minor:
                raise ValueError(f"Lossy downgrade in accounts.{name}, row {row[0]}")

    entries, transactions = tables["journal_entries"], tables["transactions"]
    leg_currency = sa.func.upper(sa.func.trim(transactions.c.currency))
    invalid = connection.execute(sa.select(entries.c.id, leg_currency).select_from(entries.join(
        transactions, transactions.c.id == entries.c.transaction_id, isouter=True,
    )).where(sa.or_(leg_currency.is_(None), leg_currency.not_in(CURRENCY_EXPONENTS)))).first()
    if invalid:
        raise ValueError(f"Cannot resolve journal currency, leg {invalid[0]}: {invalid[1]!r}")
    mixed = connection.execute(sa.select(entries.c.account_id).select_from(entries.join(
        transactions, transactions.c.id == entries.c.transaction_id,
    )).group_by(entries.c.account_id).having(sa.func.count(sa.distinct(leg_currency)) > 1)).scalars().all()
    if mixed:
        logging.getLogger("alembic.runtime.migration").warning(
            "Downgrade restores a legacy mixed-currency scalar for accounts %s; it is not meaningful holdings or FX valuation.", mixed,
        )
    # The reverse is a recomputation, exact only for a single-currency account
    # within float precision. Mixed currencies reproduce legacy unit addition,
    # which cannot restore meaningful holdings or the discarded cached value.
    leg_factor = sa.case({code: 10 ** places for code, places in CURRENCY_EXPONENTS.items()}, value=leg_currency)
    sign = sa.case((accounts.c.account_type.in_(DEBIT_NORMAL_TYPES), 1), else_=-1)
    total = sa.select(sa.func.sum(
        sa.cast(entries.c.debit_minor - entries.c.credit_minor, sa.Float()) / leg_factor,
    )).select_from(entries.join(transactions, transactions.c.id == entries.c.transaction_id)).where(
        entries.c.account_id == accounts.c.id,
    ).correlate_except(entries, transactions).scalar_subquery()
    connection.execute(accounts.update().values(balance=sign * sa.func.coalesce(total, 0.0)))
    with op.batch_alter_table("accounts") as batch:
        for name in MONEY_COLUMNS:
            batch.alter_column(name, existing_type=sa.Float(), nullable=nullable[name])
            batch.drop_column(f"{name}_minor")
