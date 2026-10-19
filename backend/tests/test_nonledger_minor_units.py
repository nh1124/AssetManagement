import pytest
from datetime import date
import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, aliased

from scenario_fixtures import goal_scenario_id

from app import models, schemas
from app.database import Base
from app.domain.errors import Refused
from app.domain.money import Money
from app.models.money import MinorUnits
from app.services.capsule_service import _resolve_rule_amount
from app.services.money_storage import rule_amount_fields
from app.services.ai_policy_service import replace_client_policies
from app.workflows.ai_change_request_workflow import preview_change_request


@pytest.mark.parametrize("currency", ["JPY", "USD"])
def test_threshold_through_request_context(currency):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(models.Client(id=1, name="threshold", general_settings={"currency": currency}))
        db.commit()
        policy = replace_client_policies(db, 1, [{
            "resource": "transactions", "action": "create", "risk": "medium",
            "mode": "deny", "threshold_amount": 10000,
        }])[0]
        assert policy.threshold_amount_minor == Money.from_major("10000", currency).minor

        def request(amount):
            return schemas.AiChangeRequestPreviewRequest(
                resource="transactions", action="create", risk="medium",
                input_payload={"date": "2026-10-12", "amount": amount,
                               "description": "threshold probe", "currency": currency},
            )

        assert preview_change_request(db, 1, request(9999))["validation"]["valid"]
        with pytest.raises(Refused, match=f"Matched policy {policy.id}"):
            preview_change_request(db, 1, request(10001))
        print(f"Threshold {currency}: 10000 major; request 9999 does not fire, 10001 fires")


MONEY_FIELDS = [
    (models.MonthlyPlanLine, "amount"), (models.LifeEvent, "target_amount"),
    (models.Capsule, "target_amount"),
    (models.Capsule, "monthly_contribution"), (models.MonthlyAction, "amount"),
    (models.Product, "last_unit_price"), (models.Product, "purchase_price"),
    (models.AiOperationPolicy, "threshold_amount"),
    (models.RegistryEntry, "amount"),
]


@pytest.mark.parametrize("model,field", MONEY_FIELDS + [(models.CapsuleRule, "amount_value")])
def test_old_names_refuse_writes(model, field):
    with pytest.raises(AttributeError):
        setattr(model(), field, 1.25)


@pytest.mark.parametrize("model,field", MONEY_FIELDS + [(models.CapsuleRule, "amount")])
@pytest.mark.parametrize("value", [1.25, True, "125"])
def test_minor_binder_refuses_nonintegers(model, field, value):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        column = model.__table__.c[f"{field}_minor"]
        assert isinstance(column.type, MinorUnits)
        with pytest.raises(StatementError, match="minor units must be a plain integer"):
            connection.execute(model.__table__.update().values({column.name: value}))
    if model in (models.MonthlyPlanLine, models.Capsule, models.Product) and value == 1.25:
        print(f"Fractional {model.__tablename__}.{field}_minor=1.25 refused at SQLAlchemy bind by MinorUnits")


@pytest.mark.parametrize("kind,minor,bp", [
    ("fixed", 1, 250), ("fixed", None, None),
    ("percentage", 1, 250), ("percentage", None, None),
    ("fixed", None, 250), ("percentage", 1, None), ("other", 1, None),
])
def test_rule_check_refuses_invalid_split(kind, minor, bp):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError, match="ck_capsule_rule_amount_kind"):
            connection.execute(models.CapsuleRule.__table__.insert().values(
                client_id=1, capsule_id=1, trigger_type="Expense", amount_type=kind,
                amount_minor=minor, percentage_bp=bp,
            ))
    print(f"Rule {kind}, amount_minor={minor}, percentage_bp={bp}: CHECK refuses")


@pytest.mark.parametrize("currency,expected", [("JPY", 3), ("USD", 2.53)])
def test_fractional_percentage_keeps_b2_rounding(currency, expected):
    rule = models.CapsuleRule(amount_type="percentage", percentage_bp=250)
    assert rule.amount_value == 2.5
    assert _resolve_rule_amount(rule, 101, currency=currency) == expected
    with pytest.raises(ValueError, match="basis points"):
        rule_amount_fields(2.501, "percentage", currency)


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/20261012_0052_nonledger_minor_units.py"
    spec = importlib.util.spec_from_file_location("b6_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_nullable(name, column):
    if name == "recurring_transactions":
        return True
    if name == "capsule_holdings":
        return False
    if (name, column) == ("capsules", "current_balance"):
        return True
    table = Base.metadata.tables.get(name)
    # Tables and columns retired since this migration were nullable when it ran.
    if table is None or f"{column}_minor" not in table.c:
        return True
    return table.c[f"{column}_minor"].nullable


def _old_database(currency="JPY"):
    migration = _migration()
    metadata = sa.MetaData()
    sa.Table("clients", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("general_settings", sa.JSON))
    for name, columns in migration.MONEY_COLUMNS.items():
        foreign = "capsule_id" if name == "capsule_holdings" else "client_id"
        fields = [sa.Column("id", sa.Integer, primary_key=True), sa.Column(foreign, sa.Integer)]
        if name in ("registry_entries", "recurring_transactions"):
            fields.append(sa.Column("currency", sa.String, nullable=False))
        fields.extend(sa.Column(column, sa.Float, nullable=_legacy_nullable(name, column),
                                server_default="0" if (name, column) in migration.ZERO_DEFAULTS else None)
                      for column in columns)
        sa.Table(name, metadata, *fields)
    sa.Table("capsule_rules", metadata, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("client_id", sa.Integer), sa.Column("capsule_id", sa.Integer),
             sa.Column("amount_type", sa.String, nullable=False), sa.Column("amount_value", sa.Float, nullable=False))
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(metadata.tables["clients"].insert(), [
            {"id": 1, "general_settings": {"currency": currency}},
            {"id": 2, "general_settings": {"currency": "EUR"}},
        ])
        for name, columns in migration.MONEY_COLUMNS.items():
            fields = {"id": 1, "capsule_id" if name == "capsule_holdings" else "client_id": 1}
            fields.update({column: 1200.0 for column in columns})
            if name in ("registry_entries", "recurring_transactions"):
                fields["currency"] = "USD"
            connection.execute(metadata.tables[name].insert().values(**fields))
            if "client_id" in fields:
                fields.update(id=2, client_id=2)
                fields.update({column: 12.34 for column in columns})
                if "currency" in fields:
                    fields["currency"] = "JPY"
                    fields.update({column: 12.0 for column in columns})
                connection.execute(metadata.tables[name].insert().values(**fields))
        connection.execute(metadata.tables["capsule_rules"].insert(), [
            {"id": 1, "client_id": 1, "capsule_id": 1, "amount_type": "fixed", "amount_value": 8808.0},
            {"id": 2, "client_id": 1, "capsule_id": 1, "amount_type": "percentage", "amount_value": 2.5},
        ])
    return engine


def _run_migration(engine, direction):
    with engine.begin() as connection:
        # Explicit BEGIN makes rejection roll back SQLite DDL as well as data.
        connection.exec_driver_sql("BEGIN")
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_migration(), direction)()


def _snapshot(engine):
    with engine.connect() as connection:
        return {name: [dict(row) for row in connection.execute(sa.text(f"SELECT * FROM {name} ORDER BY id")).mappings()]
                for name in (*_migration().MONEY_COLUMNS, "capsule_rules")}


@pytest.mark.parametrize("currency", ["JPY", "USD"])
def test_migration_applies_and_reverses_all_listed_columns(currency):
    engine = _old_database(currency)
    before = _snapshot(engine)
    _run_migration(engine, "upgrade")
    after = _snapshot(engine)
    for name, columns in _migration().MONEY_COLUMNS.items():
        for column in columns:
            metadata = {col["name"]: col for col in sa.inspect(engine).get_columns(name)}
            assert column not in metadata
            assert isinstance(metadata[f"{column}_minor"]["type"], sa.BigInteger)
            assert metadata[f"{column}_minor"]["nullable"] == _legacy_nullable(name, column)
            if (name, column) in _migration().ZERO_DEFAULTS:
                assert metadata[f"{column}_minor"]["default"] == "0"
            for old, new in zip(before[name], after[name]):
                denomination = old.get("currency") or (currency if old.get("client_id", 1) == 1 else "EUR")
                assert new[f"{column}_minor"] == Money.from_major(str(old[column]), denomination).minor
    assert after["capsule_rules"][0]["amount_minor"] == Money.from_major("8808", currency).minor
    assert after["capsule_rules"][0]["percentage_bp"] is None
    assert after["capsule_rules"][1]["amount_minor"] is None
    assert after["capsule_rules"][1]["percentage_bp"] == 250
    _run_migration(engine, "downgrade")
    back = _snapshot(engine)
    assert back == before
    for name in ("monthly_plan_lines", "capsules", "capsule_rules"):
        print(f"Migration {currency} {name}: before={before[name][0]}, after={after[name][0]}, back={back[name][0]}")
    print(f"Migration {currency} percentage: {before['capsule_rules'][1]} -> {after['capsule_rules'][1]} -> {back['capsule_rules'][1]}")


@pytest.mark.parametrize("damage,message", [
    ("UPDATE clients SET general_settings = '{}' WHERE id = 1", "Cannot resolve supported currency"),
    ("UPDATE clients SET general_settings = '{\"currency\":\"GBP\"}' WHERE id = 1", "Cannot resolve supported currency"),
    ("UPDATE monthly_plan_lines SET client_id = 999 WHERE id = 1", "Cannot resolve supported currency"),
    ("UPDATE capsule_holdings SET capsule_id = 999 WHERE id = 1", "Cannot resolve supported currency"),
    ("UPDATE monthly_plan_lines SET amount = 1.25 WHERE id = 1", "Lossy conversion"),
    ("UPDATE capsule_rules SET amount_value = 2.501 WHERE id = 2", "Lossy conversion"),
    ("UPDATE capsule_rules SET amount_type = 'other' WHERE id = 1", "Invalid capsule rule"),
    ("UPDATE monthly_plan_lines SET amount = 1e20 WHERE id = 1", "overflow"),
])
def test_migration_rejects_without_guessing_or_rounding(damage, message):
    engine = _old_database()
    with engine.begin() as connection:
        connection.execute(sa.text(damage))
    before = _snapshot(engine)
    with pytest.raises(ValueError, match=message):
        _run_migration(engine, "upgrade")
    assert _snapshot(engine) == before


def test_projected_monthly_savings_round_but_recorded_registry_amount_aborts(caplog):
    engine = _old_database()
    values = [58899.40549998684, 57719.2299119962]
    with engine.begin() as connection:
        for row_id, value in enumerate(values, start=1):
            connection.execute(sa.text(
                "UPDATE simulation_scenarios SET client_id = 1, monthly_savings = :value WHERE id = :id"
            ), {"id": row_id, "value": value})
        connection.execute(sa.text("UPDATE simulation_configs SET monthly_savings = 2.5 WHERE id = 1"))
        connection.execute(sa.text("UPDATE simulation_configs SET monthly_savings = -2.505 WHERE id = 2"))
    with caplog.at_level("INFO", logger="alembic.runtime.migration"):
        _run_migration(engine, "upgrade")
    after = _snapshot(engine)
    assert [row["monthly_savings_minor"] for row in after["simulation_scenarios"]] == [58899, 57719]
    assert [row["monthly_savings_minor"] for row in after["simulation_configs"]] == [3, -251]
    for value, row in zip(values, after["simulation_scenarios"]):
        assert f"{value} -> {row['monthly_savings_minor']} minor" in caplog.text
        print(f"Projected monthly_savings JPY: {value} -> {row['monthly_savings_minor']}")
    print("HALF_UP projections: JPY 2.5 -> 3; EUR -2.505 -> -251 minor (-2.51 major)")
    _run_migration(engine, "downgrade")
    assert [row["monthly_savings"] for row in _snapshot(engine)["simulation_scenarios"]] == [58899.0, 57719.0]

    recorded = _old_database()
    with recorded.begin() as connection:
        connection.execute(sa.text("UPDATE simulation_scenarios SET monthly_savings = :value WHERE id = 1"),
                           {"value": values[0]})
        connection.execute(sa.text("UPDATE registry_entries SET amount = 1.25 WHERE id = 2"))
    before = _snapshot(recorded)
    with pytest.raises(ValueError, match=r"Lossy conversion in registry_entries\.amount, row 2"):
        _run_migration(recorded, "upgrade")
    assert _snapshot(recorded) == before
    print("Recorded registry_entries.amount JPY: 1.25 -> migration aborts; all changes roll back")


def _money_rows(db):
    db.add(models.Client(id=1, name="money reads", general_settings={"currency": "USD"}))
    db.add(models.Account(id=1, client_id=1, name="cash", account_type="asset"))
    db.flush()
    rows = [
        models.LifeEvent(scenario_id=goal_scenario_id(db, 1), id=1, client_id=1, target_amount_minor=1234),
        models.Capsule(id=1, client_id=1, target_amount_minor=1234,
                       monthly_contribution_minor=1234),
        models.MonthlyPlanLine(id=1, client_id=1, target_period="2026-10", line_type="expense", amount_minor=1234),
        models.MonthlyAction(id=1, client_id=1, source_period="2026-10", proposal_id="read",
                             kind="set_budget", idempotency_key="read", amount_minor=1234),
        models.Product(id=1, client_id=1, last_unit_price_minor=1234, purchase_price_minor=1234),
        models.AiOperationPolicy(id=1, client_id=1, resource="transactions", action="create",
                                 risk="medium", mode="deny", threshold_amount_minor=1234),
        models.RegistryEntry(id=1, client_id=1, name='read', currency='JPY', amount_minor=1234, start_date=date(2026, 1, 1), repeat_mode="indefinite", frequency="Monthly"),
        models.CapsuleRule(id=1, client_id=1, capsule_id=1, trigger_type="Expense", amount_type="fixed", amount_minor=1234),
        models.CapsuleRule(id=2, client_id=1, capsule_id=1, trigger_type="Expense", amount_type="percentage", percentage_bp=250),
    ]
    db.add_all(rows)
    db.commit()
    return {type(row): row for row in rows if not isinstance(row, models.CapsuleRule)}


@pytest.mark.parametrize("model,field", MONEY_FIELDS)
def test_major_reads_and_sql_expressions_keep_currency(model, field):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        row = _money_rows(db)[model]
        expected = 1234 if model in (models.RegistryEntry,) else 12.34
        assert getattr(row, field) == expected
        assert db.query(getattr(model, field)).filter(model.id == row.id).scalar() == expected
        alias = aliased(model)
        assert db.query(sa.func.sum(getattr(alias, field))).scalar() == expected
        assert db.query(model).filter(getattr(model, field) == expected).one().id == row.id
        query = db.query(getattr(model, field)).join(models.Client, model.client_id == models.Client.id)
        assert query.scalar() == expected


def test_rule_major_sql_reads_and_type_switch_clear_other_column():
    from app.services.capsule_service import update_rule
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _money_rows(db)
        assert db.query(models.CapsuleRule.amount_value).order_by(models.CapsuleRule.id).all() == [(12.34,), (2.5,)]
        rule = update_rule(db, 1, 1, schemas.CapsuleRuleUpdate(amount_type="percentage", amount_value=2.5))
        assert (rule.amount_minor, rule.percentage_bp, rule.amount_value) == (None, 250, 2.5)
        rule = update_rule(db, 1, 1, schemas.CapsuleRuleUpdate(amount_type="fixed", amount_value=12.34))
        assert (rule.amount_minor, rule.percentage_bp, rule.amount_value) == (1234, None, 12.34)


def test_missing_owner_is_refused_for_runtime_reads_and_writes():
    from app.services.goal_service import create_goal_record
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        from app.domain.errors import NotFound
        with pytest.raises(NotFound, match="シナリオが見つかりません"):
            create_goal_record(db, 999, schemas.LifeEventCreate(scenario_id=999, name="orphan", target_amount=100, target_date="2027-01-01"))
        with pytest.raises(ValueError, match="Cannot resolve client currency"):
            _ = models.Capsule(client_id=None, target_amount_minor=100).target_amount


def test_downgrade_refuses_lossy_float():
    engine = _old_database()
    _run_migration(engine, "upgrade")
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE monthly_plan_lines SET amount_minor = :amount WHERE id = 1"),
                           {"amount": 2 ** 53 + 1})
    before = _snapshot(engine)
    with pytest.raises(ValueError, match="Lossy downgrade"):
        _run_migration(engine, "downgrade")
    assert _snapshot(engine) == before


def test_foreign_threshold_context_values_in_client_currency_and_requires_rate():
    from app.domain.errors import Invalid
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(models.Client(id=1, name="JPY threshold", general_settings={"currency": "JPY"}))
        db.commit()
        replace_client_policies(db, 1, [{
            "resource": "transactions", "action": "create", "risk": "medium",
            "mode": "deny", "threshold_amount": 10000,
        }])

        def request(amount):
            return schemas.AiChangeRequestPreviewRequest(
                resource="transactions", action="create", risk="medium",
                input_payload={"date": "2026-10-12", "amount": amount, "currency": "USD"},
            )

        with pytest.raises(Invalid, match="without an exchange rate"):
            preview_change_request(db, 1, request(66.68))
        db.add(models.ExchangeRate(client_id=1, base_currency="USD", quote_currency="JPY",
                                   rate=150, as_of_date=date(2026, 10, 12)))
        db.commit()
        assert preview_change_request(db, 1, request(66.66))["validation"]["valid"]
        with pytest.raises(Refused, match="Matched policy"):
            preview_change_request(db, 1, request(66.68))


@pytest.mark.parametrize("value", [1.25, True, "250", 2 ** 31])
def test_basis_point_binding_is_integer_and_bounded(value):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        with pytest.raises(StatementError):
            connection.execute(models.CapsuleRule.__table__.update().values(percentage_bp=value))


def test_migration_preserves_nullable_amounts():
    engine = _old_database()
    with engine.begin() as connection:
        for name, columns in _migration().MONEY_COLUMNS.items():
            for column in columns:
                if _legacy_nullable(name, column):
                    connection.execute(sa.text(f"UPDATE {name} SET {column} = NULL"))
    before = _snapshot(engine)
    _run_migration(engine, "upgrade")
    after = _snapshot(engine)
    for name, columns in _migration().MONEY_COLUMNS.items():
        for column in columns:
            if _legacy_nullable(name, column):
                assert all(row[f"{column}_minor"] is None for row in after[name])
    _run_migration(engine, "downgrade")
    assert _snapshot(engine) == before


def test_migration_unset_currency_all_null_succeeds_but_value_rolls_back():
    engine = _old_database()
    nullable_tables = {"products": ("last_unit_price", "purchase_price"),
                       "ai_operation_policies": ("threshold_amount",)}
    with engine.begin() as connection:
        metadata = sa.MetaData()
        metadata.reflect(bind=connection)
        connection.execute(metadata.tables["clients"].insert().values(id=3, general_settings={}))
        for name, columns in nullable_tables.items():
            connection.execute(metadata.tables[name].insert().values(
                id=3, client_id=3, **dict.fromkeys(columns, None),
            ))
    before = _snapshot(engine)
    _run_migration(engine, "upgrade")
    after = _snapshot(engine)
    for name, columns in nullable_tables.items():
        assert all(after[name][-1][f"{column}_minor"] is None for column in columns)
    _run_migration(engine, "downgrade")
    assert _snapshot(engine) == before

    for direction, suffix in (("upgrade", ""), ("downgrade", "_minor")):
        if direction == "downgrade":
            _run_migration(engine, "upgrade")
        for name, columns in nullable_tables.items():
            for column in columns:
                field = f"{column}{suffix}"
                with engine.begin() as connection:
                    connection.execute(sa.text(f"UPDATE {name} SET {field} = 0 WHERE id = 3"))
                before = _snapshot(engine)
                schema_before = {table: sa.inspect(engine).get_columns(table) for table in nullable_tables}
                with pytest.raises(ValueError, match=f"^Cannot resolve supported currency in {name}, row 3: None$"):
                    _run_migration(engine, direction)
                assert _snapshot(engine) == before
                for table, schema in schema_before.items():
                    assert [col["name"] for col in sa.inspect(engine).get_columns(table)] == [col["name"] for col in schema]
                with engine.begin() as connection:
                    connection.execute(sa.text(f"UPDATE {name} SET {field} = NULL WHERE id = 3"))
    _run_migration(engine, "downgrade")
    engine.dispose()
