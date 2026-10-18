from datetime import datetime

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship

from ..database import Base


class TransactionBatch(Base):
    __tablename__ = "transaction_batches"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    label = Column(String, nullable=True)
    source = Column(String, default="quick", server_default="quick", nullable=False)
    input_payload = Column(JSON, default=dict, server_default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="transaction_batches")
    transactions = relationship("Transaction", back_populates="batch")
