from sqlalchemy import Column, Integer, Float, ForeignKey, Boolean, CheckConstraint
from sqlalchemy.orm import relationship

from ..database import Base

class SimulationConfig(Base):
    __tablename__ = "simulation_configs"
    __table_args__ = (CheckConstraint("horizon_years BETWEEN 1 AND 60", name="ck_simulation_configs_horizon_years"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    user_id = Column(Integer, default=1)
    annual_return = Column(Float, default=5.0)
    tax_rate = Column(Float, default=20.0)
    is_nisa = Column(Boolean, default=True)
    volatility = Column(Float, default=15.0)
    inflation_rate = Column(Float, default=2.0)
    horizon_years = Column(Integer, nullable=False, default=30, server_default="30")

    client = relationship("Client", back_populates="simulation_configs")
