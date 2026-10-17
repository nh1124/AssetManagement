"""Own saved branches, projection assumptions and the client's chosen goal."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import NoReturn

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound, Refused
from .life_event_conditions import evaluate_projection
from .life_event_walk import ScenarioEvent, walk_scenarios, _subtract_demand
from .strategy_service import simulate_net_worth_forward_with_paths


@dataclass(frozen=True)
class ResolvedScenario:
    events: list[ScenarioEvent]
    missing_forks: list[int]
    chosen_link_ids: list[int]


def _refuse(message: str) -> NoReturn:
    raise Refused(message, status_code=422)


def _lock(db: Session, client_id: int):
    # The client lock serializes name checks and goal switching, even with no goal yet.
    if db.query(models.Client).filter_by(id=client_id).with_for_update().first() is None:
        raise NotFound("クライアントが見つかりません。")


def get(db: Session, client_id: int, scenario_id: int) -> models.LifeScenario:
    scenario = db.query(models.LifeScenario).filter_by(id=scenario_id, client_id=client_id).first()
    if scenario is None:
        raise NotFound("シナリオが見つかりません。")
    return scenario


def get_goal(db: Session, client_id: int) -> models.LifeScenario | None:
    return db.query(models.LifeScenario).filter_by(client_id=client_id, is_goal=True).first()


def _owned(client_id: int, scenario: models.LifeScenario | None) -> None:
    if scenario is not None and scenario.client_id != client_id:
        raise NotFound("シナリオが見つかりません。")


def choice_ids(db: Session, scenario: models.LifeScenario | None) -> list[int]:
    return [link_id for (link_id,) in db.query(models.LifeScenarioChoice.link_id).filter_by(
        scenario_id=scenario.id,
    ).order_by(models.LifeScenarioChoice.link_id).all()] if scenario else []


def account_returns(db: Session, scenario: models.LifeScenario | None) -> list[dict]:
    return [{"account_id": account_id, "annual_return": rate} for account_id, rate in db.query(
        models.LifeScenarioAccountReturn.account_id, models.LifeScenarioAccountReturn.annual_return,
    ).filter_by(scenario_id=scenario.id).order_by(models.LifeScenarioAccountReturn.account_id).all()] if scenario else []


def resolve(db: Session, client_id: int, scenario: models.LifeScenario | None) -> ResolvedScenario:
    _owned(client_id, scenario)
    walks, missing = walk_scenarios(db, client_id, set(choice_ids(db, scenario)))
    walk = walks[0]
    return ResolvedScenario(walk.events, missing, walk.chosen_link_ids)


def _payload(db: Session, scenario: models.LifeScenario, resolved: ResolvedScenario) -> dict:
    return {
        **{field: getattr(scenario, field) for field in (
            "id", "client_id", "name", "annual_return", "inflation", "horizon_years", "is_goal", "created_at", "updated_at",
        )},
        "choices": choice_ids(db, scenario),
        "account_returns": account_returns(db, scenario),
        "events": [asdict(event) for event in resolved.events],
        "missing_forks": resolved.missing_forks,
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
    db.add(scenario)
    db.flush()
    for link_id in choice_ids(db, source):
        db.add(models.LifeScenarioChoice(scenario_id=scenario.id, link_id=link_id))
    _copy_returns(db, scenario, source)
    db.commit()
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


def _replace_choices(db, client_id, scenario, link_ids):
    ids = set(link_ids)
    links = db.query(models.LifeEventLink).filter(
        models.LifeEventLink.client_id == client_id, models.LifeEventLink.id.in_(ids),
    ).all()
    if len(links) != len(ids) or any(link.kind != "alternative" for link in links):
        _refuse("同じクライアントの分岐の接続を選択してください。")
    if len({link.from_event_id for link in links}) != len(links):
        _refuse("同じ分岐では接続を1つだけ選択してください。")
    db.query(models.LifeScenarioChoice).filter_by(scenario_id=scenario.id).delete(synchronize_session="fetch")
    for link_id in sorted(ids):
        db.add(models.LifeScenarioChoice(scenario_id=scenario.id, link_id=link_id))
    scenario.updated_at = datetime.utcnow()


def replace_choices(db: Session, client_id: int, scenario_id: int, link_ids: list[int]) -> models.LifeScenario:
    _lock(db, client_id)
    scenario = get(db, client_id, scenario_id)
    _replace_choices(db, client_id, scenario, link_ids)
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


def make_goal(db: Session, client_id: int, scenario_id: int) -> models.LifeScenario:
    _lock(db, client_id)
    scenario = get(db, client_id, scenario_id)
    # Flush the previous goal first: the partial unique index applies per statement.
    previous = get_goal(db, client_id)
    if previous is not None and previous.id != scenario.id:
        previous.is_goal = False
        db.flush()
    scenario.is_goal = True
    db.commit()
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


def seed_legacy_goal(db: Session, client_id: int, adopted_link_ids: list[int]) -> models.LifeScenario | None:
    """Convert pre-LS1 facts without committing; the importer owns its transaction."""
    if not db.query(models.LifeEvent.id).filter_by(client_id=client_id).first():
        return None
    parameters = legacy_parameters(db, client_id)
    links = db.query(models.LifeEventLink).filter(
        models.LifeEventLink.client_id == client_id, models.LifeEventLink.kind == "alternative",
        models.LifeEventLink.id.in_(adopted_link_ids),
    ).order_by(models.LifeEventLink.id).all()
    names = {event.id: event.name for event in db.query(models.LifeEvent).filter_by(client_id=client_id).all()}
    name = " ／ ".join(names[link.to_event_id] for link in links) or "基本シナリオ"
    # Imported legacy goals may collide with scenario names already in the backup.
    base_name, suffix = name, 2
    while db.query(models.LifeScenario.id).filter_by(client_id=client_id, name=name).first():
        name = f"{base_name} ({suffix})"
        suffix += 1
    scenario = models.LifeScenario(
        client_id=client_id, name=name,
        annual_return=parameters["annual_return"], inflation=parameters["inflation"],
        horizon_years=parameters["years"], is_goal=True,
    )
    db.add(scenario)
    db.flush()
    for link in links:
        db.add(models.LifeScenarioChoice(scenario_id=scenario.id, link_id=link.id))
    for account in db.query(models.Account).filter(
        models.Account.client_id == client_id, models.Account.account_type == "asset", models.Account.expected_return.isnot(None),
    ).all():
        db.add(models.LifeScenarioAccountReturn(scenario_id=scenario.id, account_id=account.id, annual_return=account.expected_return))
    return scenario
