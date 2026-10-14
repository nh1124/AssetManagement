from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Integer,
    String, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from sqlalchemy.ext.hybrid import hybrid_property

from ..domain.money import Money
from .money import MinorUnits, major_expression, client_currency, client_currency_expression
from ..database import Base

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "depreciation_method IN ('none', 'straight_line', 'declining_balance')",
            name="ck_product_depreciation_method",
        ),
        CheckConstraint(
            "depreciation_interval IN ('monthly', 'yearly')",
            name="ck_product_depreciation_interval",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    name = Column(String, index=True)
    category = Column(String)
    location = Column(String, nullable=True)
    last_unit_price_minor = Column(MinorUnits)
    units_per_purchase = Column(Integer, nullable=True, default=1)
    frequency_days = Column(Integer, default=0)
    last_purchase_date = Column(Date, nullable=True)
    is_asset = Column(Boolean, default=False)
    lifespan_months = Column(Integer, nullable=True)
    budget_account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    funding_capsule_id = Column(Integer, ForeignKey("capsules.id", ondelete="SET NULL"), nullable=True)
    budget_treatment = Column(String, nullable=False, default="auto")
    # Depreciation tracking
    purchase_price_minor = Column(MinorUnits, nullable=True)
    purchase_date = Column(Date, nullable=True)
    # How this asset is written down, and where the entry lands. The direct
    # method is used: the expense is debited and the item account credited, so
    # no contra-asset account type is needed. The original cost stays in
    # purchase_price_minor, which is what the indirect method preserves.
    depreciation_method = Column(String, nullable=False, default="none", server_default="none")
    depreciation_annual_rate = Column(Float, nullable=True)
    depreciation_interval = Column(String, nullable=False, default="monthly", server_default="monthly")
    depreciation_start_date = Column(Date, nullable=True)
    depreciation_expense_account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )
    depreciation_asset_account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )

    client = relationship("Client", back_populates="products")
    budget_account = relationship("Account", foreign_keys=[budget_account_id])
    funding_capsule = relationship("Capsule", foreign_keys=[funding_capsule_id])

    @hybrid_property
    def last_unit_price(self) -> float | None:
        if self.last_unit_price_minor is None:
            return None
        return Money(self.last_unit_price_minor, client_currency(self)).to_float()

    @last_unit_price.expression
    def last_unit_price(cls):
        return major_expression(cls.last_unit_price_minor, client_currency_expression(cls))

    @hybrid_property
    def purchase_price(self) -> float | None:
        if self.purchase_price_minor is None:
            return None
        return Money(self.purchase_price_minor, client_currency(self)).to_float()

    @purchase_price.expression
    def purchase_price(cls):
        return major_expression(cls.purchase_price_minor, client_currency_expression(cls))


class ProductDepreciation(Base):
    """One posted write-down, and the entry that carried it.

    The book value is always the purchase price less the sum of these rows, read
    from the ledger rather than from a stored running total, so the figure cannot
    drift from the entries that produced it. The unique constraint is what stops
    a period being written down twice.
    """

    __tablename__ = "product_depreciations"
    __table_args__ = (
        UniqueConstraint("client_id", "product_id", "period", name="uq_product_depreciation_period"),
    )

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String, nullable=False)
    # A posting about an entry that no longer exists is a statement about nothing.
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    amount_minor = Column(MinorUnits, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    transaction = relationship("Transaction")
