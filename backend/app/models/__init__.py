"""Models grouped by the aggregate owning each table in test_table_ownership.py.

No module here imports another: SQLAlchemy resolves relationships by name
through Base, and this package registers every model before mapper configuration.
"""

from ..database import Base
from .client import Client, ClientMfaSetting, ClientRecoveryCode
from .ledger import AccountType, AccountRole, Account, JournalEntry, Transaction, TransactionProposal
from .template import QuickTemplate, TransactionBatch
from .fx import ExchangeRate
from .product import Product
from .registry import RecurringTransaction, RegistryEntry
from .goal import LifeEvent, Milestone
from .budget import BudgetPlan, MonthlyPlanLine
from .planning import PeriodReview, MonthlyAction, PeriodClose
from .ai import AiOperationPolicy, AiAuditLog, AiChangeRequest
from .simulation import SimulationConfig, SimulationScenario
from .capsule import Capsule, CapsuleFundingSource, CapsuleRule, CapsuleDrawdown

__all__ = [
    "Base",
    "Client",
    "ClientMfaSetting",
    "ClientRecoveryCode",
    "AccountType",
    "AccountRole",
    "Account",
    "JournalEntry",
    "Transaction",
    "TransactionProposal",
    "QuickTemplate",
    "TransactionBatch",
    "ExchangeRate",
    "Product",
    "RecurringTransaction",
    "RegistryEntry",
    "LifeEvent",
    "Milestone",
    "BudgetPlan",
    "MonthlyPlanLine",
    "PeriodReview",
    "PeriodClose",
    "MonthlyAction",
    "AiOperationPolicy",
    "AiAuditLog",
    "AiChangeRequest",
    "SimulationConfig",
    "SimulationScenario",
    "Capsule",
    "CapsuleFundingSource",
    "CapsuleRule",
    "CapsuleDrawdown",
]
