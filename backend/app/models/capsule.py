from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship

from ..database import Base

class Capsule(Base):
    __tablename__ = "capsules"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, index=True)
    target_amount = Column(Float)
    monthly_contribution = Column(Float)
    current_balance = Column(Float, default=0.0)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    # The capsule decides whether its reservations need a decision; the vocabulary
    # deliberately matches RecurringTransaction.auto_post.
    auto_post = Column(Boolean, default=False, server_default="false", nullable=False)
    capsule_type = Column(String, default="manual", server_default="manual", nullable=False)
    target_amount_source = Column(String, default="manual", server_default="manual", nullable=False)
    monthly_contribution_source = Column(String, default="manual", server_default="manual", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="capsules")
    account = relationship("Account", foreign_keys=[account_id])
    life_event = relationship("LifeEvent", back_populates="capsules")
    holdings = relationship("CapsuleHolding", back_populates="capsule", cascade="all, delete-orphan")


class CapsuleRule(Base):
    __tablename__ = "capsule_rules"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False)
    trigger_type = Column(String, nullable=False)
    trigger_category = Column(String, nullable=True)
    trigger_description = Column(String, nullable=True)
    source_mode = Column(String, default="transaction_account", nullable=False)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    amount_type = Column(String, default="fixed", nullable=False)
    amount_value = Column(Float, default=0.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="capsule_rules")
    capsule = relationship("Capsule")
    source_account = relationship("Account", foreign_keys=[source_account_id])


class CapsuleHolding(Base):
    __tablename__ = "capsule_holdings"

    id = Column(Integer, primary_key=True, index=True)
    capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    held_amount = Column(Float, nullable=False, default=0.0)
    note = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    capsule = relationship("Capsule", back_populates="holdings")
    account = relationship("Account")
