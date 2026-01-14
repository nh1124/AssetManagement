from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client

router = APIRouter(prefix="/simulation", tags=["simulation"])

@router.get("/config", response_model=schemas.SimulationConfig)
def get_simulation_config(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Get simulation config for current client."""
    config = db.query(models.SimulationConfig).filter(models.SimulationConfig.client_id == current_client.id).first()
    if not config:
        return schemas.SimulationConfig(
            id=0,
            annual_return=5.0,
            monthly_savings=100000,
            tax_rate=20.0,
            is_nisa=True
        )
    return config

@router.post("/config", response_model=schemas.SimulationConfig)
def create_or_update_simulation_config(
    config: schemas.SimulationConfigCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Create or update simulation config for current client."""
    db_config = db.query(models.SimulationConfig).filter(models.SimulationConfig.client_id == current_client.id).first()
    if db_config:
        for key, value in config.model_dump().items():
            setattr(db_config, key, value)
    else:
        db_config = models.SimulationConfig(**config.model_dump(), client_id=current_client.id)
        db.add(db_config)
    
    db.commit()
    db.refresh(db_config)
    return db_config

@router.put("/config", response_model=schemas.SimulationConfig)
def update_simulation_config(
    config: schemas.SimulationConfigCreate, 
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client)
):
    """Shortcut for create_or_update."""
    return create_or_update_simulation_config(config, db, current_client)

