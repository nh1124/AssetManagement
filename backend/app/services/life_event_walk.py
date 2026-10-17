"""Resolve a scenario's own events in deterministic dependency order."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from heapq import heappop, heappush

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Refused
from .money_storage import money_client_currency
from .strategy_service import aggregate_event_demand_by_year


@dataclass(frozen=True)
class ScenarioEvent:
    id: int
    name: str
    resolved_date: date | None
    target_amount: float
    currency: str
    incoming_link_id: int | None
    direction: str = "expense"
    account_id: int | None = None


def _offset_date(source: date | None, months: int) -> date | None:
    if source is None:
        return None
    year, month = divmod(source.year * 12 + source.month - 1 + months, 12)
    if not 1 <= year <= 9999:
        raise Refused("接続の月数が日付の範囲を超えています。", status_code=422)
    return date(year, month + 1, min(source.day, monthrange(year, month + 1)[1]))


def walk(db: Session, client_id: int, scenario_id: int) -> list[ScenarioEvent]:
    events = {event.id: event for event in db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id, models.LifeEvent.scenario_id == scenario_id,
        models.LifeEvent.archived_at.is_(None),
    ).order_by(models.LifeEvent.id).all()}
    outgoing: dict[int, list[models.LifeEventLink]] = {event_id: [] for event_id in events}
    indegree = dict.fromkeys(events, 0)
    for link in db.query(models.LifeEventLink).filter_by(client_id=client_id).order_by(models.LifeEventLink.id).all():
        # Archiving removes the node and its incident edges from this simulation only.
        if link.from_event_id in events and link.to_event_id in events:
            outgoing[link.from_event_id].append(link)
            indegree[link.to_event_id] += 1
    roots = {event_id for event_id, degree in indegree.items() if degree == 0}
    ready = sorted(roots)
    order = []
    while ready:
        event_id = heappop(ready)
        order.append(event_id)
        for link in outgoing[event_id]:
            indegree[link.to_event_id] -= 1
            if indegree[link.to_event_id] == 0:
                heappush(ready, link.to_event_id)
    if len(order) != len(events):
        raise Refused("イベントの接続が循環しています。", status_code=422)

    resolved: dict[int, ScenarioEvent] = {}
    incoming: dict[int, models.LifeEventLink] = {}
    currency = money_client_currency(db, client_id)
    # The lowest incoming link id determines a merge date; each event counts once.
    for event_id in order:
        event = events[event_id]
        link = incoming.get(event_id)
        resolved_date = event.target_date
        if link is not None and link.offset_months:
            resolved_date = _offset_date(resolved[link.from_event_id].resolved_date, link.offset_months)
        resolved[event_id] = ScenarioEvent(
            event.id, event.name, resolved_date, event.target_amount or 0.0, currency,
            link.id if link else None, event.direction, event.account_id,
        )
        for edge in outgoing[event_id]:
            if edge.to_event_id not in incoming or edge.id < incoming[edge.to_event_id].id:
                incoming[edge.to_event_id] = edge
    return list(resolved.values())


def _subtract_demand(scenario, projection: list[dict], years: int) -> list[dict]:
    demand = aggregate_event_demand_by_year(
        [(event.resolved_date, event.target_amount) for event in scenario.events if event.direction == "expense"], years,
        income_events=[(event.resolved_date, event.target_amount) for event in scenario.events if event.direction == "income"],
    )
    return [
        {**row, "cumulative_target": due["cumulative_target"],
         "cumulative_income": due["cumulative_income"],
         **{band: row[band] - due["cumulative_target"] + due["cumulative_income"] for band in ("p10", "p50", "p90")}}
        for row, due in zip(projection, demand)
    ]


