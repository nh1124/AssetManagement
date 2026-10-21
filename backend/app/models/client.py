from datetime import datetime

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, JSON, Text
from sqlalchemy.orm import relationship

from ..database import Base

class Client(Base):
    """SaaS Client/User: Owns a subset of data. Matches VisionArk's User + UserSettings pattern."""
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True, nullable=True) # For login
    email = Column(String, unique=True, index=True, nullable=True)    # For login/recovery
    password_hash = Column(String, nullable=True)                    # Bcrypt hash
    general_settings = Column(JSON, default=dict) # { "currency": "JPY", "language": "ja" }
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


    # Relationships
    accounts = relationship("Account", back_populates="client")
    transactions = relationship("Transaction", back_populates="client")
    transaction_batches = relationship("TransactionBatch", back_populates="client")
    products = relationship("Product", back_populates="client")
    life_events = relationship("LifeEvent", back_populates="client")
    simulation_configs = relationship("SimulationConfig", back_populates="client")
    registry_entries = relationship("RegistryEntry", back_populates="client")
    capsules = relationship("Capsule", back_populates="client")
    capsule_rules = relationship("CapsuleRule", back_populates="client")
    monthly_plan_lines = relationship("MonthlyPlanLine", back_populates="client")
    budget_plans = relationship("BudgetPlan", back_populates="client")
    period_reviews = relationship("PeriodReview", back_populates="client")
    exchange_rates = relationship("ExchangeRate", back_populates="client")
    mfa_setting = relationship("ClientMfaSetting", back_populates="client", uselist=False, cascade="all, delete-orphan")
    recovery_codes = relationship("ClientRecoveryCode", back_populates="client", cascade="all, delete-orphan")
    ai_operation_policies = relationship(
        "AiOperationPolicy",
        back_populates="client",
        cascade="all, delete-orphan",
        foreign_keys="AiOperationPolicy.client_id",
    )
    ai_audit_logs = relationship(
        "AiAuditLog",
        back_populates="client",
        cascade="all, delete-orphan",
        foreign_keys="AiAuditLog.client_id",
    )
    ai_change_requests = relationship(
        "AiChangeRequest",
        back_populates="client",
        cascade="all, delete-orphan",
        foreign_keys="AiChangeRequest.client_id",
    )


class ClientMfaSetting(Base):
    __tablename__ = "client_mfa_settings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), unique=True, nullable=False, index=True)
    totp_secret_encrypted = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    enabled_at = Column(DateTime, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="mfa_setting")


class ClientRecoveryCode(Base):
    __tablename__ = "client_recovery_codes"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    client = relationship("Client", back_populates="recovery_codes")
