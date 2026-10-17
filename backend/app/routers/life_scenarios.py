"""HTTP adapters for user-authored life scenarios."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import life_scenario_service as service
from ..workflows.scenario_goal_workflow import choose_goal

router = APIRouter(prefix="/life-scenarios", tags=["life_scenarios"])


@router.get("")
def list_scenarios(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return service.list_scenarios(db, current_client.id)


@router.get("/compare")
def compare(
    ids: str,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return service.compare(db, current_client.id, ids)


@router.post("")
def create(
    payload: schemas.LifeScenarioName,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = service.create(db, current_client.id, payload.name)
    return service.describe(db, current_client.id, scenario)


@router.post("/{scenario_id}/duplicate")
def duplicate(
    scenario_id: int,
    payload: schemas.LifeScenarioName,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = service.duplicate(db, current_client.id, scenario_id, payload.name)
    return service.describe(db, current_client.id, scenario)


@router.put("/{scenario_id}")
def update(
    scenario_id: int,
    payload: schemas.LifeScenarioUpdate,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = service.update(db, current_client.id, scenario_id, payload.model_dump(exclude_unset=True))
    return service.describe(db, current_client.id, scenario)


@router.put("/{scenario_id}/account-returns")
def account_returns(
    scenario_id: int,
    payload: schemas.LifeScenarioAccountReturns,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = service.replace_account_returns(
        db, current_client.id, scenario_id, [row.model_dump() for row in payload.returns],
    )
    return service.describe(db, current_client.id, scenario)


@router.get("/{scenario_id}/goal-preview")
def goal_preview(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return service.goal_preview(db, current_client.id, scenario_id)


@router.post("/{scenario_id}/goal")
def goal(
    scenario_id: int,
    payload: schemas.LifeScenarioGoal = schemas.LifeScenarioGoal(),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = choose_goal(db, current_client.id, scenario_id, confirm_detach=payload.confirm_detach)
    return service.describe(db, current_client.id, scenario)


@router.delete("/{scenario_id}")
def delete(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    service.delete(db, current_client.id, scenario_id)
    return {"message": "削除しました。"}
