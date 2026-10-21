"""Models grouped by the aggregate owning each table in test_table_ownership.py.

No module here imports another: SQLAlchemy resolves relationships by name
through Base, and this package registers every model before mapper configuration.
"""

from ..database import Base
from .client import Client, ClientMfaSetting, ClientRecoveryCode
from .ledger import AccountType, Account, JournalEntry, Transaction, TransactionProposal
from .transaction_batch import TransactionBatch
from .fx import ExchangeRate, FxTrackedCurrency
from .product import Product, ProductDepreciation
from .registry import RegistryEntry
from .goal import (
    GoalBudgetReflection, LifeScenario, LifeEvent, LifeEventLink, HouseholdMember, LifeEventCondition, ScenarioAssumptionPeriod,
    ScenarioContributionPlan,
)
from .budget import BudgetPlan, MonthlyPlanLine
from .planning import PeriodReview, MonthlyAction, PeriodClose
from .ai import AiOperationPolicy, AiAuditLog, AiChangeRequest
from .simulation import SimulationConfig
from .capsule import Capsule, CapsuleFundingSource, CapsuleRule, CapsuleDrawdown
from .notification import Notification

__all__ = [
    "Base",
    "Client",
    "ClientMfaSetting",
    "ClientRecoveryCode",
    "AccountType",
    "Account",
    "JournalEntry",
    "Transaction",
    "TransactionProposal",
    "TransactionBatch",
    "ExchangeRate",
    "FxTrackedCurrency",
    "Product",
    "ProductDepreciation",
    "RegistryEntry",
    "GoalBudgetReflection",
    "LifeScenario",
    "ScenarioContributionPlan",
    "ScenarioAssumptionPeriod",
    "LifeEvent",
    "LifeEventLink",
    "HouseholdMember",
    "LifeEventCondition",
    "BudgetPlan",
    "MonthlyPlanLine",
    "PeriodReview",
    "PeriodClose",
    "MonthlyAction",
    "AiOperationPolicy",
    "AiAuditLog",
    "AiChangeRequest",
    "SimulationConfig",
    "Capsule",
    "CapsuleFundingSource",
    "CapsuleRule",
    "CapsuleDrawdown",
    "Notification",
]
