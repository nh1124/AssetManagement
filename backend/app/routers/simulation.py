from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/simulation", tags=["simulation"])

@router.get("/config", response_model=schemas.SimulationConfig)
def get_simulation_config(db: Session = Depends(get_db)):
    config = db.query(models.SimulationConfig).first()
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
def create_or_update_simulation_config(config: schemas.SimulationConfigCreate, db: Session = Depends(get_db)):
    db_config = db.query(models.SimulationConfig).first()
    if db_config:
        for key, value in config.model_dump().items():
            setattr(db_config, key, value)
    else:
        db_config = models.SimulationConfig(**config.model_dump())
        db.add(db_config)
    
    db.commit()
    db.refresh(db_config)
    return db_config

@router.put("/config", response_model=schemas.SimulationConfig)
def update_simulation_config(config: schemas.SimulationConfigCreate, db: Session = Depends(get_db)):
    return create_or_update_simulation_config(config, db)
