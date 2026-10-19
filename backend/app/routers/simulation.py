from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.cache_service import invalidate_client
from ..services.simulation_config_service import get_config, upsert_config

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/config", response_model=schemas.SimulationConfig)
def get_simulation_config(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Client-wide simulation settings (tax, volatility); defaults until saved."""
    config = get_config(db, current_client.id)
    if not config:
        return schemas.SimulationConfig(id=0, annual_return=5.0, tax_rate=20.0, is_nisa=True, volatility=15.0, inflation_rate=2.0)
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
