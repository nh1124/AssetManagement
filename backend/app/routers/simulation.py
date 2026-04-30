from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.simulation_service import (
    calculate_current_funded_and_weighted_return,
    calculate_goal_probability_monte_carlo,
    run_monte_carlo,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/config", response_model=schemas.SimulationConfig)
def get_simulation_config(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Get simulation config for current client."""
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == current_client.id
    ).first()
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
    db_config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == current_client.id
    ).first()
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
    current_client: models.Client = Depends(get_current_client),
):
    """Shortcut for create_or_update."""
    return create_or_update_simulation_config(config, db, current_client)


@router.post("/monte-carlo/{life_event_id}", response_model=schemas.MonteCarloResult)
def monte_carlo_simulation(
    life_event_id: int,
    n_simulations: int = Query(default=1000, ge=100, le=10000),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Run Monte Carlo simulation for a life event."""
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == current_client.id,
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")

    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == current_client.id
    ).first()

    annual_return = config.annual_return if config else 5.0
    volatility = config.volatility if config else 15.0
    inflation_rate = config.inflation_rate if config else 2.0
    monthly_savings = config.monthly_savings if config else 50000.0

    current_funded, weighted_return = calculate_current_funded_and_weighted_return(event)
    effective_return = weighted_return if event.allocations else annual_return
    years_remaining = max(0.0, (event.target_date - date.today()).days / 365.25)

    mc_result = run_monte_carlo(
        current_funded=current_funded,
        monthly_savings=monthly_savings,
        years_remaining=years_remaining,
        annual_return=effective_return,
        volatility=volatility,
        inflation_rate=inflation_rate,
        n_simulations=n_simulations,
    )
    probability = calculate_goal_probability_monte_carlo(
        current_funded=current_funded,
        monthly_savings=monthly_savings,
        years_remaining=years_remaining,
        target_amount=event.target_amount,
        annual_return=effective_return,
        volatility=volatility,
        inflation_rate=inflation_rate,
        n_simulations=n_simulations,
    )

    return {
        "life_event_id": life_event_id,
        "life_event_name": event.name,
        "target_amount": event.target_amount,
        "years_remaining": round(years_remaining, 1),
        "probability": probability,
        "percentiles": mc_result["percentiles"],
        "year_by_year": mc_result["year_by_year"],
        "n_simulations": n_simulations,
    }
