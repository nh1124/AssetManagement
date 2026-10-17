"""Explicit scenario ownership for tests written before stories owned events."""
from app import models


def goal_scenario_id(db, client_id):
    db.flush()
    scenario = db.query(models.LifeScenario).filter_by(client_id=client_id, is_goal=True).first()
    if scenario is None:
        scenario = models.LifeScenario(client_id=client_id, name="基本シナリオ", is_goal=True)
        db.add(scenario)
        db.flush()
    return scenario.id
