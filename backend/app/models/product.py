from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from ..database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    category = Column(String)
    location = Column(String, nullable=True)
    last_unit_price = Column(Float)
    units_per_purchase = Column(Integer, nullable=True, default=1)
    frequency_days = Column(Integer, default=0)
    last_purchase_date = Column(Date, nullable=True)
    is_asset = Column(Boolean, default=False)
    lifespan_months = Column(Integer, nullable=True)
    budget_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    funding_capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="SET NULL"), nullable=True)
    budget_treatment = Column(String, nullable=False, default="auto")
    # Depreciation tracking
    purchase_price = Column(Float, nullable=True)
    purchase_date = Column(Date, nullable=True)

    client = relationship("Client", back_populates="products")
    budget_account = relationship("Account", foreign_keys=[budget_account_id])
    funding_capsule = relationship("Capsule", foreign_keys=[funding_capsule_id])
