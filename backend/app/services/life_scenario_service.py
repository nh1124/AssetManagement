"""Own complete stories, projection assumptions and the client's chosen goal."""
from __future__ import annotations

import math
from dataclasses import asdict
from typing import NoReturn

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, Refused
from .cache_service import invalidate_client
from .contribution_plan_service import copy_plans, list_plans, serialize as serialize_plan
from .event_funding_service import copy_fundings
from .goal_service import copy_events
from .life_event_conditions import copy_conditions
from .life_event_graph import copy_links
from .life_event_walk import walk
from .life_scenario_scope import get, get_goal, lock_client as _lock
from .scenario_simulation import simulate


def _refuse(message: str) -> NoReturn:
    raise Refused(message, status_code=422)


def describe(db: Session, client_id: int, scenario: models.LifeScenario) -> dict:
    return {
        **{field: getattr(scenario, field) for field in (
            "id", "client_id", "name", "annual_return", "inflation", "horizon_years", "is_goal", "created_at", "updated_at",
        )},
        "contribution_plans": [serialize_plan(db, client_id, plan) for plan in list_plans(db, client_id, scenario.id)],
        "events": [asdict(event) for event in walk(db, client_id, scenario.id)],
    }


def list_scenarios(db: Session, client_id: int) -> list[dict]:
    return [describe(db, client_id, scenario) for scenario in db.query(models.LifeScenario).filter_by(
        client_id=client_id,
    ).order_by(models.LifeScenario.id).all()]


def project(db: Session, client_id: int, scenario: models.LifeScenario) -> dict:
    result = simulate(db, client_id, scenario)
    return {**describe(db, client_id, scenario), **result}


def compare(db: Session, client_id: int, ids: str) -> dict:
    try:
        scenario_ids = [int(value.strip()) for value in ids.split(",")]
        if not scenario_ids or any(value <= 0 for value in scenario_ids):
            raise ValueError
    except (ValueError, AttributeError):
        _refuse("比較するシナリオのIDをカンマ区切りで指定してください。")
    scenarios = [get(db, client_id, scenario_id) for scenario_id in dict.fromkeys(scenario_ids)]
    return {"scenarios": [project(db, client_id, scenario) for scenario in scenarios]}


def _name(db, client_id, name, scenario_id=None):
    if not isinstance(name, str) or not name.strip():
        _refuse("シナリオ名を入力してください。")
    name = name.strip()
    query = db.query(models.LifeScenario).filter_by(client_id=client_id, name=name)
    if scenario_id is not None:
        query = query.filter(models.LifeScenario.id != scenario_id)
    if query.first() is not None:
        raise Conflict("同じ名前のシナリオが登録されています。")
    return name


def _rate(rate):
    if isinstance(rate, bool) or not isinstance(rate, (float, int)) or not math.isfinite(rate):
        _refuse("利率は有限の数値で指定してください。")
    return float(rate)


def _assumptions(scenario):
    return {field: getattr(scenario, field) for field in ("annual_return", "inflation", "horizon_years")} if scenario else {}


def create(db: Session, client_id: int, name: str) -> models.LifeScenario:
    _lock(db, client_id)
    scenario = models.LifeScenario(client_id=client_id, name=_name(db, client_id, name), **_assumptions(get_goal(db, client_id)))
    db.add(scenario)
    db.commit()
    return scenario


def duplicate(db: Session, client_id: int, scenario_id: int, name: str) -> models.LifeScenario:
    """Copy the story and its contribution plan; goal earmark tracking is not part of a story."""
    _lock(db, client_id)
    source = get(db, client_id, scenario_id)
    scenario = models.LifeScenario(client_id=client_id, name=_name(db, client_id, name), **_assumptions(source))
    try:
        db.add(scenario)
        db.flush()
        copy_graph(db, client_id, source.id, scenario.id)
        copy_plans(db, source.id, scenario.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return scenario


def update(db: Session, client_id: int, scenario_id: int, values: dict) -> models.LifeScenario:
    _lock(db, client_id)
    scenario = get(db, client_id, scenario_id)
    # Validate the complete patch before changing any loaded row.
    values = dict(values)
    if "name" in values:
        values["name"] = _name(db, client_id, values["name"], scenario_id)
    for field in ("annual_return", "inflation"):
        if field in values:
            values[field] = _rate(values[field])
    if "horizon_years" in values and (type(values["horizon_years"]) is not int or not 1 <= values["horizon_years"] <= 60):
        _refuse("試算期間は1〜60年で指定してください。")
    for field in ("name", "annual_return", "inflation", "horizon_years"):
        if field in values:
            setattr(scenario, field, values[field])
    db.commit()
    return scenario


def make_goal(db: Session, client_id: int, scenario_id: int, *, commit: bool = True) -> models.LifeScenario:
    """Mark the scenario as the goal. What happens to earmarks is goal_change_workflow's."""
    _lock(db, client_id)
    scenario = get(db, client_id, scenario_id)
    previous = get_goal(db, client_id)
    try:
        if previous is not None and previous.id != scenario.id:
            previous.is_goal = False
            db.flush()
        scenario.is_goal = True
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return scenario


def delete(db: Session, client_id: int, scenario_id: int) -> None:
    _lock(db, client_id)
    scenario = get(db, client_id, scenario_id)
    if scenario.is_goal:
        _refuse("ゴールのシナリオは削除できません。先に別のシナリオをゴールにしてください。")
    db.delete(scenario)
    db.commit()


def seed_legacy_goal(db: Session, client_id: int) -> models.LifeScenario:
    """Give a restored shared graph a goal before its events are inserted."""
    existing = get_goal(db, client_id)
    if existing is not None:
        return existing
    name, suffix = "基本シナリオ", 2
    while db.query(models.LifeScenario.id).filter_by(client_id=client_id, name=name).first():
        name = f"基本シナリオ ({suffix})"
        suffix += 1
    scenario = models.LifeScenario(client_id=client_id, name=name, is_goal=True,
                                   annual_return=5.0, inflation=2.0, horizon_years=30)
    db.add(scenario)
    db.flush()
    return scenario


def copy_graph(db: Session, client_id: int, source_id: int, target_id: int) -> dict[int, int]:
    """Copy story facts through their owners; real-money earmarks stay put."""
    get(db, client_id, source_id)
    get(db, client_id, target_id)
    event_map = copy_events(db, client_id, source_id, target_id)
    copy_links(db, client_id, event_map)
    copy_conditions(db, client_id, event_map)
    copy_fundings(db, event_map)
    return event_map
