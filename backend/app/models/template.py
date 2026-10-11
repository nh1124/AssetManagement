from datetime import datetime

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, JSON
from sqlalchemy.orm import relationship

from ..database import Base

class QuickTemplate(Base):
    __tablename__ = "quick_templates"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    tray = Column(String, index=True, nullable=False)
    name = Column(String, index=True, nullable=False)
    template_kind = Column(String, nullable=False)
    description = Column(String, nullable=True)
    category = Column(String, nullable=True)
    default_currency = Column(String, default="JPY", server_default="JPY", nullable=False)
    default_from_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    default_to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    config = Column(JSON, default=dict, server_default="{}", nullable=False)
    sort_order = Column(Integer, default=0, server_default="0", nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="quick_templates")
    default_from_account = relationship("Account", foreign_keys=[default_from_account_id])
    default_to_account = relationship("Account", foreign_keys=[default_to_account_id])
    batches = relationship("TransactionBatch", back_populates="template")


class TransactionBatch(Base):
    __tablename__ = "transaction_batches"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    quick_template_id = Column(Integer, ForeignKey("quick_templates.id"), nullable=True)
    label = Column(String, nullable=True)
    source = Column(String, default="quick", server_default="quick", nullable=False)
    input_payload = Column(JSON, default=dict, server_default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="transaction_batches")
    template = relationship("QuickTemplate", back_populates="batches")
    transactions = relationship("Transaction", back_populates="batch")
