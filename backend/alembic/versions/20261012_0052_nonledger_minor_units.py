"""Store nonledger money in minor units and separate capsule rule percentages."""
from alembic import op
from decimal import Decimal, ROUND_HALF_UP
import logging
import sqlalchemy as sa

from app.domain.money import CURRENCY_EXPONENTS, Money

revision = "20261012_0052"
down_revision = "20261012_0051"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "monthly_plan_lines": ("amount",),
    "life_events": ("target_amount",),
    "milestones": ("target_amount",),
    "capsules": ("target_amount", "monthly_contribution", "current_balance"),
    "capsule_holdings": ("held_amount",),
    "monthly_actions": ("amount",),
    "products": ("last_unit_price", "purchase_price"),
    "simulation_configs": ("monthly_savings",),
    "simulation_scenarios": ("monthly_savings",),
    "ai_operation_policies": ("threshold_amount",),
    "recurring_transactions": ("amount",),
    "registry_entries": ("amount",),
}
RULE_CHECK = (
    "(amount_type = 'fixed' AND amount_minor IS NOT NULL AND percentage_bp IS NULL) OR "
    "(amount_type = 'percentage' AND amount_minor IS NULL AND percentage_bp IS NOT NULL)"
)
ZERO_DEFAULTS = {("monthly_plan_lines", "amount"), ("capsule_holdings", "held_amount"), ("registry_entries", "amount")}
# Projected monthly figures are computed, not recorded; sub-unit precision is
# noise from a division rather than information.
PROJECTED_MONTHLY_COLUMNS = {
    ("simulation_configs", "monthly_savings"),
    ("simulation_scenarios", "monthly_savings"),
}


def _tables():
    metadata = sa.MetaData()
    return {name: sa.Table(name, metadata, autoload_with=op.get_bind())
            for name in (*MONEY_COLUMNS, "capsule_rules", "clients")}


def _currency(table, tables):
    if table.name in ("recurring_transactions", "registry_entries"):
        return table.c.currency
    clients = tables["clients"]
    # A migration cannot use Cur1's unset-preference default to guess old denominations.
    setting = sa.func.upper(sa.func.trim(clients.c.general_settings["currency"].as_string()))
    if table.name == "capsule_holdings":
        capsules = tables["capsules"]
        return sa.select(setting).select_from(clients.join(
            capsules, capsules.c.client_id == clients.c.id,
        )).where(capsules.c.id == table.c.capsule_id).correlate_except(clients, capsules).scalar_subquery()
    return sa.select(setting).select_from(clients).where(
        clients.c.id == table.c.client_id,
    ).correlate_except(clients).scalar_subquery()


def _factor(currency):
    return sa.case({code: 10 ** places for code, places in CURRENCY_EXPONENTS.items()}, value=currency)


def _verify_currencies(connection, tables):
    for name in (*MONEY_COLUMNS, "capsule_rules"):
        table = tables[name]
        currency = _currency(table, tables)
        invalid = connection.execute(sa.select(table.c.id, currency).where(
            sa.or_(currency.is_(None), currency.not_in(CURRENCY_EXPONENTS)),
        )).first()
        if invalid:
            raise ValueError(f"Cannot resolve supported currency in {name}, row {invalid[0]}: {invalid[1]!r}")


def _verify_roundtrip(connection, table, old, new, factor):
    invalid = connection.execute(sa.select(table.c.id).where(sa.or_(
        sa.and_(old.is_(None), new.is_not(None)),
        sa.and_(old.is_not(None), sa.or_(new.is_(None), old != sa.cast(new, sa.Float) / factor)),
    ))).first()
    if invalid:
        raise ValueError(f"Lossy conversion in {table.name}.{old.name}, row {invalid[0]}")
    for row in connection.execute(sa.select(table.c.id, old, new, factor)):
        if row[1] is not None and Decimal(str(row[1])) * int(row[3]) != row[2]:
            raise ValueError(f"Lossy conversion in {table.name}.{old.name}, row {row[0]}")


def _populate(connection, table, old, new, factor):
    invalid = connection.execute(sa.select(table.c.id).where(sa.or_(
        old * factor >= float(2 ** 63), old * factor < -float(2 ** 63),
    ))).first()
    if invalid:
        raise ValueError(f"Minor-unit overflow in {table.name}.{old.name}, row {invalid[0]}")
    connection.execute(table.update().values({new.name: sa.cast(sa.func.round(old * factor), new.type)}))
    _verify_roundtrip(connection, table, old, new, factor)


def _populate_projected_monthly(connection, table, old, new, currency):
    for row in connection.execute(sa.select(table.c.id, old, currency)):
        money = None if row[1] is None else Money.from_major(str(row[1]), row[2], rounding=ROUND_HALF_UP)
        minor = None if money is None else money.minor
        if minor is not None and not -(2 ** 63) <= minor < 2 ** 63:
            raise ValueError(f"Minor-unit overflow in {table.name}.{old.name}, row {row[0]}")
        connection.execute(table.update().where(table.c.id == row[0]).values({new.name: minor}))
        if money is not None and Decimal(str(row[1])) != money.to_major():
            logging.getLogger("alembic.runtime.migration").info(
                "Rounding projected %s.%s, row %s (%s): %s -> %s minor (%s major)",
                table.name, old.name, row[0], row[2], row[1], minor, money.to_major(),
            )


def upgrade():
    connection = op.get_bind()
    tables = _tables()
    _verify_currencies(connection, tables)
    nullable = {(name, column): tables[name].c[column].nullable
                for name, columns in MONEY_COLUMNS.items() for column in columns}
    defaults = {(name, column): tables[name].c[column].server_default is not None
                for name, columns in MONEY_COLUMNS.items() for column in columns}
    for key, has_default in defaults.items():
        if has_default and key not in ZERO_DEFAULTS:
            raise ValueError(f"Unexpected money server default in {key}; currency-dependent defaults need explicit conversion")
    rules = tables["capsule_rules"]
    invalid = connection.execute(sa.select(rules.c.id).where(sa.or_(
        rules.c.amount_type.is_(None), rules.c.amount_type.not_in(("fixed", "percentage")),
        rules.c.amount_value.is_(None),
    ))).first()
    if invalid:
        raise ValueError(f"Invalid capsule rule amount kind, row {invalid[0]}")

    for name, columns in MONEY_COLUMNS.items():
        for column in columns:
            op.add_column(name, sa.Column(f"{column}_minor", sa.BigInteger(), nullable=True,
                                         server_default=sa.text("0") if defaults[name, column] else None))
    op.add_column("capsule_rules", sa.Column("amount_minor", sa.BigInteger(), nullable=True))
    op.add_column("capsule_rules", sa.Column("percentage_bp", sa.Integer(), nullable=True))
    tables = _tables()
    for name, columns in MONEY_COLUMNS.items():
        table = tables[name]
        currency = _currency(table, tables)
        factor = _factor(currency)
        for column in columns:
            if (name, column) in PROJECTED_MONTHLY_COLUMNS:
                _populate_projected_monthly(connection, table, table.c[column], table.c[f"{column}_minor"], currency)
            else:
                _populate(connection, table, table.c[column], table.c[f"{column}_minor"], factor)

    rules = tables["capsule_rules"]
    factor = sa.case((rules.c.amount_type == "percentage", 100), else_=_factor(_currency(rules, tables)))
    integer = sa.cast(sa.func.round(rules.c.amount_value * factor), sa.BigInteger)
    connection.execute(rules.update().values(
        amount_minor=sa.case((rules.c.amount_type == "fixed", integer)),
        percentage_bp=sa.case((rules.c.amount_type == "percentage", sa.cast(integer, sa.Integer))),
    ))
    value = sa.case((rules.c.amount_type == "fixed", rules.c.amount_minor), else_=rules.c.percentage_bp)
    _verify_roundtrip(connection, rules, rules.c.amount_value, value, factor)
    invalid = connection.execute(sa.select(rules.c.id).where(sa.or_(
        rules.c.percentage_bp > 2 ** 31 - 1, rules.c.percentage_bp < -(2 ** 31),
        rules.c.amount_value * factor >= float(2 ** 63), rules.c.amount_value * factor < -float(2 ** 63),
    ))).first()
    if invalid:
        raise ValueError(f"Capsule rule integer overflow, row {invalid[0]}")

    # Batch mode supplies SQLite's missing ALTER COLUMN without changing PostgreSQL's path.
    for name, columns in MONEY_COLUMNS.items():
        with op.batch_alter_table(name) as batch:
            for column in columns:
                batch.alter_column(f"{column}_minor", existing_type=sa.BigInteger(), nullable=nullable[name, column])
                batch.drop_column(column)
    with op.batch_alter_table("capsule_rules") as batch:
        batch.drop_column("amount_value")
        batch.create_check_constraint("ck_capsule_rule_amount_kind", RULE_CHECK)


def downgrade():
    connection = op.get_bind()
    tables = _tables()
    _verify_currencies(connection, tables)
    nullable = {(name, column): tables[name].c[f"{column}_minor"].nullable
                for name, columns in MONEY_COLUMNS.items() for column in columns}
    defaults = {(name, column): tables[name].c[f"{column}_minor"].server_default is not None
                for name, columns in MONEY_COLUMNS.items() for column in columns}
    for name, columns in MONEY_COLUMNS.items():
        for column in columns:
            op.add_column(name, sa.Column(column, sa.Float(), nullable=True,
                                         server_default=sa.text("0") if defaults[name, column] else None))
    op.add_column("capsule_rules", sa.Column("amount_value", sa.Float(), nullable=True))
    tables = _tables()
    for name, columns in MONEY_COLUMNS.items():
        table = tables[name]
        currency = _currency(table, tables)
        factor = _factor(currency)
        for column in columns:
            connection.execute(table.update().values({column: sa.cast(table.c[f"{column}_minor"], sa.Float) / factor}))
            for row in connection.execute(sa.select(table.c.id, table.c[column], table.c[f"{column}_minor"], currency)):
                if row[2] is not None and Decimal(str(row[1])) * 10 ** CURRENCY_EXPONENTS[row[3]] != row[2]:
                    raise ValueError(f"Lossy downgrade in {name}.{column}, row {row[0]}")

    rules = tables["capsule_rules"]
    factor = sa.case((rules.c.amount_type == "percentage", 100), else_=_factor(_currency(rules, tables)))
    value = sa.case((rules.c.amount_type == "fixed", rules.c.amount_minor), else_=rules.c.percentage_bp)
    connection.execute(rules.update().values(amount_value=sa.cast(value, sa.Float) / factor))
    for row in connection.execute(sa.select(rules.c.id, rules.c.amount_value, value, factor)):
        if Decimal(str(row[1])) * int(row[3]) != row[2]:
            raise ValueError(f"Lossy capsule rule downgrade, row {row[0]}")

    for name, columns in MONEY_COLUMNS.items():
        with op.batch_alter_table(name) as batch:
            for column in columns:
                batch.alter_column(column, existing_type=sa.Float(), nullable=nullable[name, column])
                batch.drop_column(f"{column}_minor")
    with op.batch_alter_table("capsule_rules") as batch:
        batch.drop_constraint("ck_capsule_rule_amount_kind", type_="check")
        batch.alter_column("amount_value", existing_type=sa.Float(), nullable=False, server_default=sa.text("0"))
        batch.drop_column("amount_minor")
        batch.drop_column("percentage_bp")
