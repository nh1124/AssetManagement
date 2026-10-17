"""HTTP adapters for the goal baseline and its comparison with actual net worth."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..domain.errors import Refused
from ..services import goal_baseline_service as service

router = APIRouter(prefix="/goal-baselines", tags=["goal_baselines"])


@router.get("/current")
def current(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """The current baseline month by month, with actual month-end net worth."""
    return service.comparison(db, current_client.id)


@router.get("")
def history(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return service.history(db, current_client.id)


@router.post("")
def capture(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    """Freeze today's goal projection as the new baseline; earlier ones stay as history."""
    if service.capture_now(db, current_client.id, "manual") is None:
        raise Refused("ゴールのシナリオがありません。シナリオ一覧でゴールを選んでください。", status_code=422)
    return service.comparison(db, current_client.id)
