"""DB-backed save/load for simulation scenarios per goal, plus comparison endpoint."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import simulation_scenario_service

router = APIRouter(
    prefix="/simulation/scenarios",
    tags=["simulation_scenarios"],
    dependencies=[Depends(get_current_client)],
)


@router.get("", response_model=List[schemas.SimulationScenario])
def list_scenarios(
    life_event_id: int = Query(..., description="Filter by life_event_id"),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return simulation_scenario_service.list_scenarios(db, current_client.id, life_event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("", response_model=schemas.SimulationScenario)
def create_scenario(
    payload: schemas.SimulationScenarioCreate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return simulation_scenario_service.create_scenario(db, current_client.id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{scenario_id}", response_model=schemas.SimulationScenario)
def update_scenario(
    scenario_id: int,
    payload: schemas.SimulationScenarioUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = simulation_scenario_service.update_scenario(db, current_client.id, scenario_id, payload)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.delete("/{scenario_id}", response_model=schemas.SimulationScenario)
def delete_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = simulation_scenario_service.delete_scenario(db, current_client.id, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.post("/compare", response_model=List[schemas.SimulationScenarioCompareItem])
def compare_scenarios(
    payload: schemas.SimulationScenarioCompareRequest,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    try:
        return simulation_scenario_service.compare_scenarios(db, current_client.id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
