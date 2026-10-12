"""Store ledger amounts in currency minor units."""
from alembic import op
import sqlalchemy as sa

from app.domain.money import CURRENCY_EXPONENTS, Money
from app.domain.journal import Leg, validate_legs

revision = "20261012_0051"
down_revision = "20261011_0050"
branch_labels = None
depends_on = None


def _tables():
    metadata = sa.MetaData()
    return tuple(sa.Table(name, metadata, autoload_with=op.get_bind()) for name in (
        "transactions", "journal_entries", "transaction_proposals",
    ))


def _factor(currency):
    return sa.case(
        {code: 10 ** places for code, places in CURRENCY_EXPONENTS.items()},
        value=currency,
    )


def _verify_currencies(connection, *tables):
    for table in tables:
        invalid = connection.execute(sa.select(table.c.id, table.c.currency).where(
            sa.or_(table.c.currency.is_(None), table.c.currency.not_in(CURRENCY_EXPONENTS)),
        )).first()
        if invalid:
            raise ValueError(f"Unsupported currency in {table.name}: {tuple(invalid)!r}")


def _verify_round_trip(connection, table, old, minor, factor):
    invalid = connection.execute(sa.select(table.c.id).where(sa.or_(
        old.is_(None), minor.is_(None), old != sa.cast(minor, sa.Float) / factor,
    ))).first()
    if invalid:
        # Existing books must not be silently rounded by a representation change.
        raise ValueError(f"Lossy minor-unit conversion in {table.name}, row {invalid[0]}")


def upgrade():
    for table, names in (
        ("transactions", ("amount_minor",)),
        ("journal_entries", ("debit_minor", "credit_minor")),
        ("transaction_proposals", ("amount_minor",)),
    ):
        for name in names:
            op.add_column(table, sa.Column(name, sa.BigInteger(), nullable=True))

    connection = op.get_bind()
    transactions, entries, proposals = _tables()
    _verify_currencies(connection, transactions, proposals)
    tx_factor = _factor(transactions.c.currency)
    leg_factor = sa.select(tx_factor).where(
        transactions.c.id == entries.c.transaction_id,
    ).correlate_except(transactions).scalar_subquery()
    proposal_factor = _factor(proposals.c.currency)

    for table, factor, pairs in (
        (transactions, tx_factor, (("amount", "amount_minor"),)),
        (entries, leg_factor, (("debit", "debit_minor"), ("credit", "credit_minor"))),
        (proposals, proposal_factor, (("amount", "amount_minor"),)),
    ):
        connection.execute(table.update().values({
            minor: sa.cast(sa.func.round(table.c[old] * factor), sa.BigInteger)
            for old, minor in pairs
        }))
        for old, minor in pairs:
            _verify_round_trip(connection, table, table.c[old], table.c[minor], factor)

    totals = sa.select(
        entries.c.transaction_id.label("id"),
        sa.func.count().label("legs"),
        sa.func.sum(entries.c.debit_minor).label("debit"),
        sa.func.sum(entries.c.credit_minor).label("credit"),
    ).group_by(entries.c.transaction_id).subquery()
    invalid = connection.execute(sa.select(transactions.c.id).select_from(
        transactions.outerjoin(totals, transactions.c.id == totals.c.id),
    ).where(sa.or_(
        totals.c.legs.is_(None), totals.c.legs < 2,
        totals.c.debit != totals.c.credit,
        totals.c.debit != transactions.c.amount_minor,
    ))).first()
    if invalid:
        raise ValueError(f"Minor-unit journal invariant failed for transaction {invalid[0]}")

    for row in connection.execute(sa.select(proposals)).mappings():
        legs = [{
            **leg,
            "debit": Money.from_major(str(leg.get("debit") or 0), row["currency"]).minor,
            "credit": Money.from_major(str(leg.get("credit") or 0), row["currency"]).minor,
        } for leg in row["legs"]]
        for old, new in zip(row["legs"], legs):
            for side in ("debit", "credit"):
                if float(old.get(side) or 0) != Money(new[side], row["currency"]).to_float():
                    raise ValueError(f"Lossy proposal leg conversion, proposal {row['id']}")
        validate_legs([Leg(**leg) for leg in legs], row["amount_minor"])
        connection.execute(proposals.update().where(proposals.c.id == row["id"]).values(legs=legs))

    # Batch mode supplies SQLite's missing ALTER COLUMN while PostgreSQL uses ALTER.
    for name, pairs in (
        ("transactions", (("amount", "amount_minor"),)),
        ("journal_entries", (("debit", "debit_minor"), ("credit", "credit_minor"))),
        ("transaction_proposals", (("amount", "amount_minor"),)),
    ):
        with op.batch_alter_table(name) as batch:
            for old, minor in pairs:
                batch.alter_column(minor, existing_type=sa.BigInteger(), nullable=False)
            for old, minor in pairs:
                batch.drop_column(old)


def downgrade():
    for name, columns in (
        ("transactions", ("amount",)),
        ("journal_entries", ("debit", "credit")),
        ("transaction_proposals", ("amount",)),
    ):
        for column in columns:
            op.add_column(name, sa.Column(column, sa.Float(), nullable=True))

    connection = op.get_bind()
    transactions, entries, proposals = _tables()
    _verify_currencies(connection, transactions, proposals)
    tx_factor = _factor(transactions.c.currency)
    leg_factor = sa.select(tx_factor).where(
        transactions.c.id == entries.c.transaction_id,
    ).correlate_except(transactions).scalar_subquery()
    for table, factor, pairs in (
        (transactions, tx_factor, (("amount", "amount_minor"),)),
        (entries, leg_factor, (("debit", "debit_minor"), ("credit", "credit_minor"))),
        (proposals, _factor(proposals.c.currency), (("amount", "amount_minor"),)),
    ):
        connection.execute(table.update().values({
            old: sa.cast(table.c[minor], sa.Float) / factor for old, minor in pairs
        }))
        for old, minor in pairs:
            invalid = connection.execute(sa.select(table.c.id).where(
                sa.cast(sa.func.round(table.c[old] * factor), sa.BigInteger) != table.c[minor],
            )).first()
            if invalid:
                raise ValueError(f"Lossy downgrade in {table.name}, row {invalid[0]}")

    for row in connection.execute(sa.select(proposals)).mappings():
        legs = [{
            **leg,
            "debit": Money(leg["debit"], row["currency"]).to_float(),
            "credit": Money(leg["credit"], row["currency"]).to_float(),
        } for leg in row["legs"]]
        for old, new in zip(row["legs"], legs):
            for side in ("debit", "credit"):
                if Money.from_major(str(new[side]), row["currency"]).minor != old[side]:
                    raise ValueError(f"Lossy proposal leg downgrade, proposal {row['id']}")
        connection.execute(proposals.update().where(proposals.c.id == row["id"]).values(legs=legs))

    for name, pairs in (
        ("transactions", (("amount", "amount_minor"),)),
        ("journal_entries", (("debit", "debit_minor"), ("credit", "credit_minor"))),
        ("transaction_proposals", (("amount", "amount_minor"),)),
    ):
        with op.batch_alter_table(name) as batch:
            if name == "transaction_proposals":
                batch.alter_column("amount", existing_type=sa.Float(), nullable=False)
            for old, minor in pairs:
                batch.drop_column(minor)
