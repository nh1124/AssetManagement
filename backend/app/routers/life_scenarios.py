"""HTTP adapters for user-authored life scenarios, their 積立設定 and 期間ごとの前提."""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..dependencies import get_current_client
from ..services import contribution_plan_service as plans
from ..services import life_scenario_service as service
from ..workflows import goal_change_workflow

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


@router.get("/{scenario_id}/goal-preview")
def goal_preview(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """What making this scenario the goal would do to the old goal's earmarks, for the choice (R11)."""
    return goal_change_workflow.preview(db, current_client.id, scenario_id)


@router.post("/{scenario_id}/goal")
def goal(
    scenario_id: int,
    payload: schemas.GoalChange = Body(default_factory=schemas.GoalChange),
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    scenario = goal_change_workflow.apply(db, current_client.id, scenario_id, payload.earmarks)
    return service.describe(db, current_client.id, scenario)


@router.delete("/{scenario_id}")
def delete(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    service.delete(db, current_client.id, scenario_id)
    return {"message": "削除しました。"}


@router.get("/{scenario_id}/assumption-periods")
def list_assumption_periods(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return [plans.serialize_period(row) for row in plans.list_periods(db, current_client.id, scenario_id)]


@router.post("/{scenario_id}/assumption-periods")
def create_assumption_period(
    scenario_id: int,
    payload: schemas.AssumptionPeriodInput,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return plans.serialize_period(plans.create_period(db, current_client.id, scenario_id, payload.model_dump(exclude_unset=True)))


@router.put("/assumption-periods/{period_id}")
def update_assumption_period(
    period_id: int,
    payload: schemas.AssumptionPeriodInput,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return plans.serialize_period(plans.update_period(db, current_client.id, period_id, payload.model_dump(exclude_unset=True)))


@router.delete("/assumption-periods/{period_id}")
def delete_assumption_period(
    period_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    plans.delete_period(db, current_client.id, period_id)
    return {"message": "削除しました。"}


@router.get("/{scenario_id}/contribution-plans")
def list_contribution_plans(
    scenario_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return [plans.serialize(db, current_client.id, plan) for plan in plans.list_plans(db, current_client.id, scenario_id)]


@router.post("/{scenario_id}/contribution-plans")
def create_contribution_plan(
    scenario_id: int,
    payload: schemas.ContributionPlanInput,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    plan = plans.create_plan(db, current_client.id, scenario_id, payload.model_dump(exclude_unset=True))
    return plans.serialize(db, current_client.id, plan)


@router.put("/contribution-plans/{plan_id}")
def update_contribution_plan(
    plan_id: int,
    payload: schemas.ContributionPlanInput,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    plan = plans.update_plan(db, current_client.id, plan_id, payload.model_dump(exclude_unset=True))
    return plans.serialize(db, current_client.id, plan)


@router.delete("/contribution-plans/{plan_id}")
def delete_contribution_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    plans.delete_plan(db, current_client.id, plan_id)
    return {"message": "削除しました。"}
