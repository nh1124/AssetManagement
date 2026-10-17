"""Choose the goal scenario and freeze its baseline.

The switch itself (moving capsules by lineage) is life_scenario_service's; this
workflow adds the baseline that later comparisons are measured against. A
failure to capture it must not undo a switch the user confirmed, so it is logged
and the goal page offers to capture the baseline again.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import models
from ..services import goal_baseline_service, life_scenario_service
from ..services.life_scenario_scope import get_goal

log = logging.getLogger(__name__)


def choose_goal(db: Session, client_id: int, scenario_id: int, *, confirm_detach: bool = False) -> models.LifeScenario:
    previous = get_goal(db, client_id)
    previous_id = previous.id if previous is not None else None
    scenario = life_scenario_service.make_goal(db, client_id, scenario_id, confirm_detach=confirm_detach)
    if previous_id != scenario.id or goal_baseline_service.current(db, client_id) is None:
        try:
            goal_baseline_service.capture(db, client_id, "adopted")
            db.commit()
        except Exception:
            db.rollback()
            log.exception("Goal baseline capture failed after switching client %s to scenario %s", client_id, scenario.id)
    return scenario
