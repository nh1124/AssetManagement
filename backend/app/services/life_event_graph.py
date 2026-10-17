"""Own life-event edges and enumerate bounded, deterministic scenario walks."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound, Refused
from .strategy_service import simulate_net_worth_forward

from .life_event_walk import (
    SCENARIO_LIMIT, ScenarioEvent, Scenario, ScenarioList,
    _offset_date, walk_scenarios, _subtract_demand,
)
from . import life_scenario_service


@dataclass(frozen=True)
class Adoption:
    scenario: Scenario | None
    exact: bool


def list_links(db: Session, client_id: int) -> list[models.LifeEventLink]:
    return db.query(models.LifeEventLink).filter(
        models.LifeEventLink.client_id == client_id,
    ).order_by(models.LifeEventLink.id).all()


def create_link(
    db: Session, client_id: int, *, from_event_id: int, to_event_id: int,
    kind: str, offset_months: int = 0, note: str | None = None,
) -> models.LifeEventLink:
    # Serialize graph edits so two individually valid inserts cannot form a cycle.
    client = db.query(models.Client).filter(models.Client.id == client_id).with_for_update().first()
    if client is None:
        raise NotFound("クライアントが見つかりません。")
    events = {event.id: event for event in db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id,
        models.LifeEvent.id.in_([from_event_id, to_event_id]),
    ).all()}
    if len(events) != len({from_event_id, to_event_id}):
        raise NotFound("同じクライアントのイベントを選択してください。")
    source, target = events[from_event_id], events[to_event_id]
    if source.archived_at or target.archived_at:
        raise Refused("中止・アーカイブしたイベントは接続できません。", status_code=422)
    if from_event_id == to_event_id:
        raise Refused(f"「{source.name}」自身には接続できません。", status_code=422)
    if kind not in {"after", "alternative"} or type(offset_months) is not int:
        raise Refused("接続の種類または月数が不正です。", status_code=422)
    adjacency: dict[int, list[int]] = {}
    for link in list_links(db, client_id):
        if (link.from_event_id, link.to_event_id) == (from_event_id, to_event_id):
            raise Conflict("このイベント間の接続は登録済みです。")
        adjacency.setdefault(link.from_event_id, []).append(link.to_event_id)
    pending, seen = [to_event_id], set()
    while pending:
        event_id = pending.pop()
        if event_id == from_event_id:
            raise Refused(f"「{source.name}」から「{target.name}」への接続は循環します。", status_code=422)
        if event_id not in seen:
            seen.add(event_id)
            pending.extend(adjacency.get(event_id, []))
    link = models.LifeEventLink(
        client_id=client_id, from_event_id=from_event_id, to_event_id=to_event_id,
        kind=kind, offset_months=offset_months, note=note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def delete_link(db: Session, client_id: int, link_id: int) -> None:
    link = db.query(models.LifeEventLink).filter(
        models.LifeEventLink.id == link_id, models.LifeEventLink.client_id == client_id,
    ).first()
    if link is None:
        raise NotFound("接続が見つかりません。")
    db.delete(link)
    db.commit()


def adoption_payload(adoption: Adoption) -> dict:
    return {"scenario_id": adoption.scenario.id if adoption.scenario else None, "exact": adoption.exact}


def enumerate_scenarios(db: Session, client_id: int) -> ScenarioList:
    return walk_scenarios(db, client_id, offset_date=_offset_date)[0]


def adopted_scenario(db: Session, client_id: int, scenarios: list[Scenario]) -> Adoption:
    if not scenarios:
        return Adoption(None, False)
    goal = life_scenario_service.get_goal(db, client_id)
    resolved = life_scenario_service.resolve(db, client_id, goal)
    chosen = resolved.chosen_link_ids
    branch = Scenario(
        "-".join(map(str, chosen)) or "base", "基本シナリオ", chosen, resolved.events,
    )
    # Resolution also works when the goal's branch falls outside the legacy 64 cap.
    branch = next((item for item in scenarios if item.id == branch.id), branch)
    return Adoption(branch, not resolved.missing_forks)


def adopt_scenario(db: Session, client_id: int, scenario_id: str) -> Adoption:
    # Deprecated: the frontend still submits enumerated branch ids during LS1.
    scenarios = enumerate_scenarios(db, client_id)
    scenario = next((item for item in scenarios if item.id == scenario_id), None)
    if scenario is None:
        raise Refused("選択したシナリオが見つかりません。再読み込みして選び直してください。", status_code=422)
    life_scenario_service.adopt_legacy(db, client_id, scenario)
    return adopted_scenario(db, client_id, scenarios)


def project_scenario(
    db: Session, client_id: int, scenario: Scenario, *, years: int,
    annual_return: float, inflation: float,
) -> list[dict]:
    return _subtract_demand(scenario, simulate_net_worth_forward(
        db, client_id, years=years, annual_return=annual_return, inflation=inflation,
        include_event_income=False,
    ), years)


def compare_scenarios(
    db: Session, client_id: int, *, years: int | None = None,
    annual_return: float | None = None, inflation: float | None = None,
) -> dict:
    # Deprecated: compare enumerated branches with the goal assumptions until the frontend moves.
    parameters = life_scenario_service.legacy_parameters(db, client_id)
    years = years if years is not None else parameters["years"]
    annual_return = annual_return if annual_return is not None else parameters["annual_return"]
    inflation = inflation if inflation is not None else parameters["inflation"]
    scenarios = enumerate_scenarios(db, client_id)
    adoption = adopted_scenario(db, client_id, scenarios)
    # All branches share one seeded baseline, so comparison costs one simulation.
    projection = simulate_net_worth_forward(
        db, client_id, years=years, annual_return=annual_return, inflation=inflation,
        include_event_income=False,
        **life_scenario_service.legacy_account_returns(db, client_id),
    )
    return {
        "parameters": {"years": years, "annual_return": annual_return, "inflation": inflation},
        "scenarios": [{**asdict(scenario), "projection": _subtract_demand(scenario, projection, years)} for scenario in scenarios],
        "truncated": scenarios.truncated,
        "fork_count": scenarios.fork_count,
        "adopted": adoption_payload(adoption),
    }
