"""Pin the ORM schema and public surface across the aggregate package move."""
import hashlib
import json

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import configure_mappers

from app import models
from app.database import Base


# WP23: 積立設定 records carry a kind, a destination account (口座振替), a schedule and the shortage choice.
EXPECTED_METADATA_SHA256 = "3c9302b6ac08361d808892a95abcdf324ebcdb1f6de018973ae1d86e1c331860"

MODEL_NAMES = (
    "Client", "ClientMfaSetting", "ClientRecoveryCode",
    "Account", "JournalEntry", "Transaction", "TransactionProposal",
    "TransactionBatch", "ExchangeRate", "FxTrackedCurrency", "Product",
    "RegistryEntry", "LifeEvent", "LifeEventLink", "HouseholdMember", "LifeEventCondition",
    "BudgetPlan", "MonthlyPlanLine", "PeriodReview", "MonthlyAction", "PeriodClose",
    "AiOperationPolicy", "AiAuditLog", "AiChangeRequest",
    "SimulationConfig",
    "LifeScenario", "ScenarioContributionPlan", "GoalBudgetReflection",
    "Capsule", "CapsuleFundingSource", "CapsuleRule", "CapsuleDrawdown", "Notification",
    "ProductDepreciation",
)
ENUM_NAMES = ("AccountType",)


def _metadata_snapshot():
    names = sorted(Base.metadata.tables)
    tables = {}
    for name in names:
        table = Base.metadata.tables[name]
        tables[name] = {
            "columns": [
                {
                    "name": column.name,
                    "type": str(column.type),
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "foreign_keys": sorted(
                        (
                            {
                                "target": key.target_fullname,
                                "ondelete": key.ondelete,
                                "onupdate": key.onupdate,
                            }
                            for key in column.foreign_keys
                        ),
                        key=lambda key: key["target"],
                    ),
                }
                for column in table.columns
            ],
            "primary_key": {
                "name": table.primary_key.name,
                "columns": [column.name for column in table.primary_key.columns],
            },
            "unique_constraints": sorted(
                (
                    {
                        "name": constraint.name,
                        "columns": [column.name for column in constraint.columns],
                    }
                    for constraint in table.constraints
                    if isinstance(constraint, UniqueConstraint)
                ),
                key=lambda constraint: json.dumps(constraint, sort_keys=True),
            ),
            "indexes": sorted(
                (
                    {
                        "name": index.name,
                        "columns": [column.name for column in index.columns],
                        "expressions": [str(expression) for expression in index.expressions],
                        "unique": index.unique,
                        "where": {
                            dialect: str(index.dialect_options[dialect].get("where"))
                            for dialect in ("sqlite", "postgresql")
                        },
                    }
                    for index in table.indexes
                ),
                key=lambda index: index["name"],
            ),
        }
    return {"table_names": names, "tables": tables}


def test_metadata_matches_the_minor_unit_schema():
    snapshot = _metadata_snapshot()
    assert len(snapshot["table_names"]) == 34
    assert sum(len(table["columns"]) for table in snapshot["tables"].values()) == 391
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED_METADATA_SHA256


def test_all_relationship_mappers_configure():
    configure_mappers()
    assert all(mapper.configured for mapper in Base.registry.mappers)


def test_every_model_enum_and_base_is_reexported():
    for name in (*MODEL_NAMES, *ENUM_NAMES, "Base"):
        assert name in vars(models), f"Missing models.{name}"
    assert models.Base is Base
    mapped = {
        name for name, value in vars(models).items()
        if isinstance(value, type) and hasattr(value, "__tablename__")
    }
    assert mapped == set(MODEL_NAMES)
    for name in MODEL_NAMES:
        model = getattr(models, name)
        assert model.__table__ is Base.metadata.tables[model.__tablename__]
        assert model.__mapper__.registry is Base.registry
    for name in ENUM_NAMES:
        assert issubclass(getattr(models, name), str)
        assert list(getattr(models, name))

