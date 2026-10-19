"""Own life-event edges and validate graph edits."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound, Refused
from .life_scenario_scope import selected


def list_links(db: Session, client_id: int, scenario_id: int | None = None) -> list[models.LifeEventLink]:
    scenario = selected(db, client_id, scenario_id)
    if scenario is None:
        return []
    return db.query(models.LifeEventLink).filter(
        models.LifeEventLink.client_id == client_id,
        models.LifeEventLink.from_event_id.in_(db.query(models.LifeEvent.id).filter_by(
            client_id=client_id, scenario_id=scenario.id,
        )),
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
    if source.scenario_id != target.scenario_id:
        raise Refused("同じシナリオのイベントを選択してください。", status_code=422)
    if from_event_id == to_event_id:
        raise Refused(f"「{source.name}」自身には接続できません。", status_code=422)
    if kind != "after":
        raise Refused("接続は「必ず続く」のみです。", status_code=422)
    if type(offset_months) is not int:
        raise Refused("接続の月数が不正です。", status_code=422)
    adjacency: dict[int, list[int]] = {}
    for link in list_links(db, client_id, source.scenario_id):
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


def copy_links(db: Session, client_id: int, event_map: dict[int, int]) -> dict[int, int]:
    link_map = {}
    for source in db.query(models.LifeEventLink).filter(
        models.LifeEventLink.client_id == client_id,
        models.LifeEventLink.from_event_id.in_(event_map),
        models.LifeEventLink.to_event_id.in_(event_map),
    ).order_by(models.LifeEventLink.id):
        row = models.LifeEventLink(
            client_id=client_id, from_event_id=event_map[source.from_event_id],
            to_event_id=event_map[source.to_event_id], kind="after",
            offset_months=source.offset_months, note=source.note, created_at=source.created_at,
        )
        db.add(row)
        db.flush()
        link_map[source.id] = row.id
    return link_map


def delete_link(db: Session, client_id: int, link_id: int) -> None:
    link = db.query(models.LifeEventLink).filter(
        models.LifeEventLink.id == link_id, models.LifeEventLink.client_id == client_id,
    ).first()
    if link is None:
        raise NotFound("接続が見つかりません。")
    db.delete(link)
    db.commit()
