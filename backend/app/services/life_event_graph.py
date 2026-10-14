"""Own life-event edges and enumerate bounded, deterministic scenario walks."""
from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date
from heapq import heappop, heappush

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound, Refused
from .money_storage import money_client_currency
from .strategy_service import aggregate_event_demand_by_year, simulate_net_worth_forward

SCENARIO_LIMIT = 64


@dataclass(frozen=True)
class ScenarioEvent:
    id: int
    name: str
    resolved_date: date | None
    target_amount: float
    currency: str
    incoming_link_id: int | None


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


def _offset_date(source: date | None, months: int) -> date | None:
    if source is None:
        return None
    year, month = divmod(source.year * 12 + source.month - 1 + months, 12)
    if not 1 <= year <= 9999:
        raise Refused("接続の月数が日付の範囲を超えています。", status_code=422)
    return date(year, month + 1, min(source.day, monthrange(year, month + 1)[1]))


def enumerate_scenarios(db: Session, client_id: int) -> list[Scenario]:
    events = {event.id: event for event in db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id, models.LifeEvent.archived_at.is_(None),
    ).order_by(models.LifeEvent.id).all()}
    outgoing: dict[int, list[models.LifeEventLink]] = {event_id: [] for event_id in events}
    indegree = dict.fromkeys(events, 0)
    for link in list_links(db, client_id):
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
                resolved_date = _offset_date(resolved[link.from_event_id].resolved_date, link.offset_months)
            resolved[event_id] = ScenarioEvent(
                event.id, event.name, resolved_date, event.target_amount or 0.0, currency,
                link.id if link else None,
            )
            alternatives = []
            for edge in outgoing[event_id]:
                if edge.kind == "alternative":
                    alternatives.append(edge)
                elif edge.to_event_id not in incoming or edge.id < incoming[edge.to_event_id].id:
                    incoming[edge.to_event_id] = edge
            if alternatives:
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
    return result


def _subtract_demand(scenario: Scenario, projection: list[dict], years: int) -> list[dict]:
    demand = aggregate_event_demand_by_year(
        [(event.resolved_date, event.target_amount) for event in scenario.events], years,
    )
    return [
        {**row, "cumulative_target": due["cumulative_target"],
         **{band: row[band] - due["cumulative_target"] for band in ("p10", "p50", "p90")}}
        for row, due in zip(projection, demand)
    ]


def project_scenario(
    db: Session, client_id: int, scenario: Scenario, *, years: int,
    annual_return: float, inflation: float,
) -> list[dict]:
    return _subtract_demand(scenario, simulate_net_worth_forward(
        db, client_id, years=years, annual_return=annual_return, inflation=inflation,
    ), years)


def compare_scenarios(
    db: Session, client_id: int, *, years: int, annual_return: float, inflation: float,
) -> dict:
    scenarios = enumerate_scenarios(db, client_id)
    # All branches share one seeded baseline, so comparison costs one simulation.
    projection = simulate_net_worth_forward(
        db, client_id, years=years, annual_return=annual_return, inflation=inflation,
    )
    return {
        "scenarios": [{**asdict(scenario), "projection": _subtract_demand(scenario, projection, years)} for scenario in scenarios],
        "truncated": scenarios.truncated,
        "fork_count": scenarios.fork_count,
    }
