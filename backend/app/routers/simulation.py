from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import json

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.simulation_service import (
    calculate_goal_probability_monte_carlo,
    get_goal_simulation_context,
    run_monte_carlo,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])


def _parse_contribution_schedule(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid contribution_schedule JSON") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="contribution_schedule must be a list")
    return [item for item in value if isinstance(item, dict)]


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
    annual_return: float | None = Query(default=None),
    inflation: float | None = Query(default=None),
    monthly_savings: float | None = Query(default=None, ge=0),
    contribution_schedule: str | None = Query(default=None),
    allocation_mode: str = Query(default="direct", pattern="^(weighted|direct)$"),
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

    volatility = config.volatility if config else 15.0
    context = get_goal_simulation_context(
        db,
        current_client.id,
        event,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=_parse_contribution_schedule(contribution_schedule),
        allocation_mode=allocation_mode,
    )

    mc_result = run_monte_carlo(
        current_funded=context["current_funded"],
        monthly_savings=context["allocated_monthly_savings"],
        years_remaining=context["years_remaining"],
        annual_return=context["effective_return"],
        volatility=volatility,
        inflation_rate=context["inflation_rate"],
        n_simulations=n_simulations,
    )
    probability = calculate_goal_probability_monte_carlo(
        current_funded=context["current_funded"],
        monthly_savings=context["allocated_monthly_savings"],
        years_remaining=context["years_remaining"],
        target_amount=event.target_amount,
        annual_return=context["effective_return"],
        volatility=volatility,
        inflation_rate=context["inflation_rate"],
        n_simulations=n_simulations,
    )

    return {
        "life_event_id": life_event_id,
        "life_event_name": event.name,
        "target_amount": event.target_amount,
        "years_remaining": round(context["years_remaining"], 1),
        "probability": probability,
        "percentiles": mc_result["percentiles"],
        "year_by_year": mc_result["year_by_year"],
        "n_simulations": n_simulations,
    }
