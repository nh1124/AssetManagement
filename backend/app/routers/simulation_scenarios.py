"""DB-backed save/load for simulation scenarios per goal, plus comparison endpoint."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services.strategy_service import (
    calculate_goal_probability_monte_carlo,
    calculate_projection,
    get_goal_simulation_context,
    run_monte_carlo,
)

router = APIRouter(
    prefix="/simulation/scenarios",
    tags=["simulation_scenarios"],
    dependencies=[Depends(get_current_client)],
)


def _ensure_life_event(db: Session, client_id: int, life_event_id: int) -> models.LifeEvent:
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == client_id,
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Life event not found")
    return event


def _get_scenario(db: Session, client_id: int, scenario_id: int) -> models.SimulationScenario:
    scenario = db.query(models.SimulationScenario).filter(
        models.SimulationScenario.id == scenario_id,
        models.SimulationScenario.client_id == client_id,
    ).first()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.get("", response_model=List[schemas.SimulationScenario])
def list_scenarios(
    life_event_id: int = Query(..., description="Filter by life_event_id"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    _ensure_life_event(db, current_client.id, life_event_id)
    return (
        db.query(models.SimulationScenario)
        .filter(
            models.SimulationScenario.client_id == current_client.id,
            models.SimulationScenario.life_event_id == life_event_id,
        )
        .order_by(models.SimulationScenario.created_at.desc(), models.SimulationScenario.id.desc())
        .all()
    )


@router.post("", response_model=schemas.SimulationScenario)
def create_scenario(
    payload: schemas.SimulationScenarioCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    _ensure_life_event(db, current_client.id, payload.life_event_id)
    duplicate = db.query(models.SimulationScenario).filter(
        models.SimulationScenario.client_id == current_client.id,
        models.SimulationScenario.life_event_id == payload.life_event_id,
        models.SimulationScenario.name == payload.name,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="A scenario with that name already exists for this goal")
    scenario = models.SimulationScenario(**payload.model_dump(), client_id=current_client.id)
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


@router.put("/{scenario_id}", response_model=schemas.SimulationScenario)
def update_scenario(
    scenario_id: int,
    payload: schemas.SimulationScenarioUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = _get_scenario(db, current_client.id, scenario_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(scenario, field, value)
    db.commit()
    db.refresh(scenario)
    return scenario


@router.delete("/{scenario_id}", response_model=schemas.SimulationScenario)
def delete_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = _get_scenario(db, current_client.id, scenario_id)
    db.delete(scenario)
    db.commit()
    return scenario


@router.post("/compare", response_model=List[schemas.SimulationScenarioCompareItem])
def compare_scenarios(
    payload: schemas.SimulationScenarioCompareRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    event = _ensure_life_event(db, current_client.id, payload.life_event_id)

    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == current_client.id
    ).first()
    volatility = config.volatility if config else 15.0

    items: list[dict] = []
    for scenario_id in payload.scenario_ids:
        scenario = _get_scenario(db, current_client.id, scenario_id)
        if scenario.life_event_id != event.id:
            raise HTTPException(
                status_code=400,
                detail=f"Scenario {scenario_id} does not belong to life_event {event.id}",
            )
        context = get_goal_simulation_context(
            db,
            current_client.id,
            event,
            annual_return=scenario.annual_return,
            inflation=scenario.inflation,
            monthly_savings=scenario.monthly_savings,
            contribution_schedule=list(scenario.contribution_schedule or []),
            allocation_mode=scenario.allocation_mode,
        )
        mc = run_monte_carlo(
            current_funded=context["current_funded"],
            monthly_savings=context["allocated_monthly_savings"],
            years_remaining=context["years_remaining"],
            annual_return=context["effective_return"],
            volatility=volatility,
            inflation_rate=context["inflation_rate"],
            n_simulations=1000,
        )
        probability = calculate_goal_probability_monte_carlo(
            current_funded=context["current_funded"],
            monthly_savings=context["allocated_monthly_savings"],
            years_remaining=context["years_remaining"],
            target_amount=event.target_amount,
            annual_return=context["effective_return"],
            volatility=volatility,
            inflation_rate=context["inflation_rate"],
            n_simulations=1000,
        )

        years_remaining = context["years_remaining"]
        full_years = int(years_remaining)
        deterministic_yearly: list[dict] = []
        for year in range(0, full_years + 1):
            balance = calculate_projection(
                current_funded=context["current_funded"],
                monthly_savings=context["allocated_monthly_savings"],
                years_remaining=float(year),
                annual_return=context["effective_return"],
            )
            deterministic_yearly.append({"year": year, "end_balance": round(float(balance), 0)})
        if years_remaining - full_years > 0:
            balance = calculate_projection(
                current_funded=context["current_funded"],
                monthly_savings=context["allocated_monthly_savings"],
                years_remaining=years_remaining,
                annual_return=context["effective_return"],
            )
            deterministic_yearly.append(
                {"year": round(years_remaining, 2), "end_balance": round(float(balance), 0)}
            )

        items.append(
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "target_amount": event.target_amount,
                "years_remaining": round(years_remaining, 2),
                "probability": probability,
                "percentiles": mc["percentiles"],
                "year_by_year": mc["year_by_year"],
                "deterministic_yearly": deterministic_yearly,
            }
        )

    return items
