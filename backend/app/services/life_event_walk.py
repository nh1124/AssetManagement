"""Share deterministic graph walks between saved and legacy enumerated scenarios."""
from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from heapq import heappop, heappush

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Refused
from .money_storage import money_client_currency
from .strategy_service import aggregate_event_demand_by_year

SCENARIO_LIMIT = 64


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


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    chosen_link_ids: list[int]
    events: list[ScenarioEvent]


class ScenarioList(list[Scenario]):
    # Keep the public list contract while carrying the reason a walk stopped.
    truncated: bool = False
    fork_count: int = 0


def _offset_date(source: date | None, months: int) -> date | None:
    if source is None:
        return None
    year, month = divmod(source.year * 12 + source.month - 1 + months, 12)
    if not 1 <= year <= 9999:
        raise Refused("接続の月数が日付の範囲を超えています。", status_code=422)
    return date(year, month + 1, min(source.day, monthrange(year, month + 1)[1]))


def walk_scenarios(
    db: Session, client_id: int, choices: set[int] | None = None, *,
    offset_date: Callable[[date | None, int], date | None] | None = None,
) -> tuple[ScenarioList, list[int]]:
    events = {event.id: event for event in db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id, models.LifeEvent.archived_at.is_(None),
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

    result = ScenarioList()
    missing_forks = []
    selected_ids = choices
    offset_date = offset_date or _offset_date
    result.fork_count = sum(sum(link.kind == "alternative" for link in links) > 1 for links in outgoing.values())
    currency = money_client_currency(db, client_id)
    names = {link.id: events[link.to_event_id].name for links in outgoing.values() for link in links}
    # Topological order resolves every predecessor before a shared descendant.
    # At a merge the lowest active link id owns the date; the event is charged once.
    stack: list[tuple[int, dict[int, ScenarioEvent], dict[int, models.LifeEventLink], list[int], Iterator[models.LifeEventLink] | None]] = [(0, {}, {}, [], None)]
    while stack:
        index, resolved, incoming, choices, branches = stack.pop()
        if branches is not None:
            edge = next(branches, None)
            if edge is None:
                continue
            # Resume siblings lazily: even a very wide fork needs only one copy at a time.
            stack.append((index, resolved, incoming, choices, branches))
            resolved, incoming, choices = resolved.copy(), incoming.copy(), [*choices, edge.id]
            if edge.to_event_id not in incoming or edge.id < incoming[edge.to_event_id].id:
                incoming[edge.to_event_id] = edge
        while index < len(order):
            event_id = order[index]
            index += 1
            if event_id not in roots and event_id not in incoming:
                continue
            event = events[event_id]
            link = incoming.get(event_id)
            resolved_date = event.target_date
            if link is not None and link.offset_months:
                resolved_date = offset_date(resolved[link.from_event_id].resolved_date, link.offset_months)
            resolved[event_id] = ScenarioEvent(
                event.id, event.name, resolved_date, event.target_amount or 0.0, currency,
                link.id if link else None,
                event.direction, event.account_id,
            )
            alternatives = []
            for edge in outgoing[event_id]:
                if edge.kind == "alternative":
                    alternatives.append(edge)
                elif edge.to_event_id not in incoming or edge.id < incoming[edge.to_event_id].id:
                    incoming[edge.to_event_id] = edge
            if alternatives:
                if selected_ids is not None:
                    selected = next((edge for edge in alternatives if edge.id in selected_ids), None)
                    if selected is None:
                        missing_forks.append(event_id)
                        selected = alternatives[0]
                    alternatives = [selected]
                stack.append((index, resolved, incoming, choices, iter(alternatives)))
                break
        else:
            if len(result) == SCENARIO_LIMIT:
                result.truncated = True
                break
            chosen = sorted(choices)
            result.append(Scenario(
                "-".join(map(str, chosen)) or "base",
                " ／ ".join(names[link_id] for link_id in chosen) or "基本シナリオ",
                chosen, list(resolved.values()),
            ))
    return result, missing_forks


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


