from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base

class SimulationConfig(Base):
    __tablename__ = "simulation_configs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    user_id = Column(Integer, default=1)
    annual_return = Column(Float, default=5.0)
    tax_rate = Column(Float, default=20.0)
    is_nisa = Column(Boolean, default=True)
    monthly_savings = Column(Float, default=100000)
    volatility = Column(Float, default=15.0)
    inflation_rate = Column(Float, default=2.0)

    client = relationship("Client", back_populates="simulation_configs")


class SimulationScenario(Base):
    """Saved simulation parameters for a goal: lets users compare and reload."""
    __tablename__ = "simulation_scenarios"
    __table_args__ = (
        UniqueConstraint("client_id", "life_event_id", "name", name="_client_life_event_scenario_name_uc"),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    life_event_id = Column(Integer, ForeignKey("life_events.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    annual_return = Column(Float, nullable=False)
    inflation = Column(Float, nullable=False)
    monthly_savings = Column(Float, nullable=True)
    contribution_schedule = Column(JSON, nullable=False, default=list, server_default="[]")
    allocation_mode = Column(String, nullable=False, default="direct", server_default="direct")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
