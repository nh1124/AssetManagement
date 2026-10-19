from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base

class ExchangeRate(Base):
    """Stored rates used to value journal transactions in the client base currency."""
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "base_currency",
            "quote_currency",
            "as_of_date",
            name="_client_fx_rate_date_uc",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    base_currency = Column(String, nullable=False)   # Source currency, e.g. USD
    quote_currency = Column(String, nullable=False)  # Target currency, e.g. JPY
    rate = Column(Float, nullable=False)
    as_of_date = Column(Date, nullable=False)
    source = Column(String, default="manual", server_default="manual", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="exchange_rates")


class FxTrackedCurrency(Base):
    __tablename__ = "fx_tracked_currencies"
    __table_args__ = (UniqueConstraint("client_id", "currency", name="uq_fx_tracked_client_currency"),)

    client_id = Column(Integer, ForeignKey("clients.id"), primary_key=True)
    currency = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
