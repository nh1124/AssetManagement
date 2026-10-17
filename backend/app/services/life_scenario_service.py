"""Own complete stories, projection assumptions and the client's chosen goal."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import NoReturn

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound, Refused
from .life_event_conditions import copy_conditions, evaluate_projection
from .life_event_walk import ScenarioEvent, walk, _subtract_demand
from .life_scenario_scope import get, get_goal, lock_client as _lock
from .goal_service import copy_events
from .life_event_graph import copy_links
from .milestone_service import copy_milestones
from .cache_service import invalidate_client
from .strategy_service import simulate_net_worth_forward_with_paths


@dataclass(frozen=True)
class ResolvedScenario:
    events: list[ScenarioEvent]


def _refuse(message: str) -> NoReturn:
    raise Refused(message, status_code=422)


def _owned(client_id: int, scenario: models.LifeScenario | None) -> None:
    if scenario is not None and scenario.client_id != client_id:
        raise NotFound("シナリオが見つかりません。")


def account_returns(db: Session, scenario: models.LifeScenario | None) -> list[dict]:
    return [{"account_id": account_id, "annual_return": rate} for account_id, rate in db.query(
        models.LifeScenarioAccountReturn.account_id, models.LifeScenarioAccountReturn.annual_return,
    ).filter_by(scenario_id=scenario.id).order_by(models.LifeScenarioAccountReturn.account_id).all()] if scenario else []


def resolve(db: Session, client_id: int, scenario: models.LifeScenario | None) -> ResolvedScenario:
    _owned(client_id, scenario)
    scenario = scenario or get_goal(db, client_id)
    return ResolvedScenario(walk(db, client_id, scenario.id) if scenario else [])


def _payload(db: Session, scenario: models.LifeScenario, resolved: ResolvedScenario) -> dict:
    return {
        **{field: getattr(scenario, field) for field in (
            "id", "client_id", "name", "annual_return", "inflation", "horizon_years", "is_goal", "created_at", "updated_at",
        )},
        "account_returns": account_returns(db, scenario),
        "events": [asdict(event) for event in resolved.events],
    }


def describe(db: Session, client_id: int, scenario: models.LifeScenario) -> dict:
    return _payload(db, scenario, resolve(db, client_id, scenario))


def list_scenarios(db: Session, client_id: int) -> list[dict]:
    return [describe(db, client_id, scenario) for scenario in db.query(models.LifeScenario).filter_by(
        client_id=client_id,
    ).order_by(models.LifeScenario.id).all()]


def project(db: Session, client_id: int, scenario: models.LifeScenario) -> dict:
    resolved = resolve(db, client_id, scenario)
    payload = _payload(db, scenario, resolved)
    projection, paths = simulate_net_worth_forward_with_paths(
        db, client_id, years=scenario.horizon_years, annual_return=scenario.annual_return,
        inflation=scenario.inflation, include_event_income=False,
        account_returns={row["account_id"]: row["annual_return"] for row in payload["account_returns"]},
    )
    projection = _subtract_demand(resolved, projection, scenario.horizon_years)
    return {**payload, "projection": projection,
            "conditions": evaluate_projection(db, client_id, resolved.events, projection, paths)}


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


def _copy_returns(db, scenario, source):
    for row in account_returns(db, source):
        db.add(models.LifeScenarioAccountReturn(scenario_id=scenario.id, **row))


def create(db: Session, client_id: int, name: str) -> models.LifeScenario:
    _lock(db, client_id)
    goal = get_goal(db, client_id)
    scenario = models.LifeScenario(client_id=client_id, name=_name(db, client_id, name), **_assumptions(goal))
    db.add(scenario)
    db.flush()
    _copy_returns(db, scenario, goal)
    db.commit()
    return scenario


def duplicate(db: Session, client_id: int, scenario_id: int, name: str) -> models.LifeScenario:
    _lock(db, client_id)
    source = get(db, client_id, scenario_id)
    scenario = models.LifeScenario(client_id=client_id, name=_name(db, client_id, name), **_assumptions(source))
    try:
        db.add(scenario)
        db.flush()
        copy_graph(db, client_id, source.id, scenario.id)
        _copy_returns(db, scenario, source)
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


def replace_account_returns(db: Session, client_id: int, scenario_id: int, returns: list[dict]) -> models.LifeScenario:
    _lock(db, client_id)
    scenario = get(db, client_id, scenario_id)
    ids = [row["account_id"] for row in returns]
    rates = [_rate(row["annual_return"]) for row in returns]
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset", models.Account.id.in_(ids),
    ).all()
    if len(accounts) != len(ids):
        _refuse("同じクライアントの資産口座を重複なく選択してください。")
    db.query(models.LifeScenarioAccountReturn).filter_by(scenario_id=scenario.id).delete(synchronize_session="fetch")
    for account_id, rate in zip(ids, rates):
        db.add(models.LifeScenarioAccountReturn(scenario_id=scenario.id, account_id=account_id, annual_return=rate))
    scenario.updated_at = datetime.utcnow()
    db.commit()
    return scenario


def goal_preview(db: Session, client_id: int, scenario_id: int) -> dict:
    """What making this scenario the goal would do to real money, before doing it.

    The same lineage rule as make_goal, read-only, so the user can confirm every
    capsule that moves, every one that would be detached, and which of the new
    goal's spending events would be left without a capsule.
    """
    scenario = get(db, client_id, scenario_id)
    previous = get_goal(db, client_id)
    events = db.query(models.LifeEvent).filter_by(client_id=client_id, scenario_id=scenario.id).order_by(
        models.LifeEvent.target_date, models.LifeEvent.id,
    ).all()
    by_lineage = {event.lineage: event for event in events}
    moves, detach = [], []
    if previous is not None and previous.id != scenario.id:
        receiving: set[int] = set()
        linked = db.query(models.Capsule, models.LifeEvent).join(
            models.LifeEvent, models.LifeEvent.id == models.Capsule.life_event_id,
        ).filter(models.Capsule.client_id == client_id, models.LifeEvent.client_id == client_id,
                 models.LifeEvent.scenario_id == previous.id).order_by(models.Capsule.id).all()
        for capsule, event in linked:
            target = by_lineage.get(event.lineage)
            if target is None:
                detach.append({"capsule_id": capsule.id, "capsule_name": capsule.name, "event_name": event.name})
            else:
                receiving.add(target.id)
                moves.append({"capsule_id": capsule.id, "capsule_name": capsule.name,
                              "from_event_name": event.name, "to_event_id": target.id, "to_event_name": target.name})
    else:
        # Already the goal, or the first goal: only capsules already on these events count.
        receiving = {event_id for (event_id,) in db.query(models.Capsule.life_event_id).filter(
            models.Capsule.client_id == client_id,
            models.Capsule.life_event_id.in_([event.id for event in events]),
        ).all()}
    # Income events never take a capsule, and archived ones no longer need funding.
    missing = [{"event_id": event.id, "event_name": event.name, "target_amount": event.target_amount}
               for event in events
               if event.direction == "expense" and event.archived_at is None and event.id not in receiving]
    return {"scenario_id": scenario.id, "scenario_name": scenario.name,
            "already_goal": previous is not None and previous.id == scenario.id,
            "moves": moves, "detach": detach, "missing": missing}


def make_goal(db: Session, client_id: int, scenario_id: int, confirm_detach: bool = False) -> models.LifeScenario:
    _lock(db, client_id)
    scenario = get(db, client_id, scenario_id)
    previous = get_goal(db, client_id)
    moves, detach = [], []
    if previous is not None and previous.id != scenario.id:
        targets = {event.lineage: event.id for event in db.query(models.LifeEvent).filter_by(
            client_id=client_id, scenario_id=scenario.id,
        ).all()}
        linked = db.query(models.Capsule, models.LifeEvent).join(
            models.LifeEvent, models.LifeEvent.id == models.Capsule.life_event_id,
        ).filter(models.Capsule.client_id == client_id, models.LifeEvent.client_id == client_id,
                 models.LifeEvent.scenario_id == previous.id).order_by(models.Capsule.id).all()
        for capsule, event in linked:
            target_id = targets.get(event.lineage)
            moves.append((capsule, target_id))
            if target_id is None:
                detach.append({"capsule_id": capsule.id, "capsule_name": capsule.name, "event_name": event.name})
        # Inspect the entire move before mutating anything so a 409 needs no repair.
        if detach and not confirm_detach:
            raise Conflict("紐づけ先のない取り置きの解除を確認してください。", payload={"detach": detach})
    try:
        for capsule, target_id in moves:
            # Only the FK changes; relationship removal would trigger delete-orphan.
            capsule.life_event_id = target_id
        if previous is not None and previous.id != scenario.id:
            previous.is_goal = False
            db.flush()
        scenario.is_goal = True
        db.commit()
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


def legacy_parameters(db: Session, client_id: int) -> dict:
    goal = get_goal(db, client_id)
    config = db.query(models.SimulationConfig).filter_by(client_id=client_id).order_by(models.SimulationConfig.id).first()
    return {
        "years": goal.horizon_years if goal else (config.horizon_years if config else 30),
        "annual_return": goal.annual_return if goal else (config.annual_return if config and config.annual_return is not None else 5.0),
        "inflation": goal.inflation if goal else (config.inflation_rate if config and config.inflation_rate is not None else 2.0),
    }


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
    for account in db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset", models.Account.expected_return.isnot(None),
    ).all():
        db.add(models.LifeScenarioAccountReturn(scenario_id=scenario.id, account_id=account.id, annual_return=account.expected_return))
    db.flush()
    return scenario


def copy_graph(db: Session, client_id: int, source_id: int, target_id: int) -> dict[int, int]:
    """Copy story facts through their owners; real-money capsules stay put."""
    get(db, client_id, source_id)
    get(db, client_id, target_id)
    event_map = copy_events(db, client_id, source_id, target_id)
    link_map = copy_links(db, client_id, event_map)
    copy_conditions(db, client_id, event_map)
    copy_milestones(db, client_id, event_map, link_map)
    return event_map
