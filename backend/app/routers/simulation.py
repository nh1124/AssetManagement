from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.simulation_config_service import get_config, upsert_config
from ..workflows.simulation_workflow import monte_carlo_for_goal

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/config", response_model=schemas.SimulationConfig)
def get_simulation_config(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Get simulation config for current client."""
    config = get_config(db, current_client.id)
    if not config:
        return schemas.SimulationConfig(
            id=0,
            annual_return=5.0,
            monthly_savings=100000,
            tax_rate=20.0,
            is_nisa=True,
            volatility=15.0,
            inflation_rate=2.0,
        )
    return config


@router.post("/config", response_model=schemas.SimulationConfig)
def create_or_update_simulation_config(
    config: schemas.SimulationConfigCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Create or update simulation config for current client."""
    db_config = upsert_config(db, current_client.id, config)
    invalidate_client(current_client.id)
    return db_config


@router.put("/config", response_model=schemas.SimulationConfig)
def update_simulation_config(
    config: schemas.SimulationConfigCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Shortcut for create_or_update."""
    return create_or_update_simulation_config(config, db, current_client)


@router.post("/monte-carlo/{life_event_id}", response_model=schemas.MonteCarloResult)
def monte_carlo_simulation(
    life_event_id: int,
    n_simulations: int = Query(default=1000, ge=100, le=10000),
    annual_return: float | None = Query(default=None),
    inflation: float | None = Query(default=None),
    monthly_savings: float | None = Query(default=None, ge=0),
    contribution_schedule: str | None = Query(default=None),
    allocation_mode: str = Query(default="direct", pattern="^(weighted|direct)$"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Run Monte Carlo simulation for a life event."""
    return monte_carlo_for_goal(
        db,
        current_client.id,
        life_event_id,
        n_simulations=n_simulations,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=contribution_schedule,
        allocation_mode=allocation_mode,
    )
