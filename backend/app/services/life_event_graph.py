"""Own life-event edges and validate graph edits."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, NotFound, Refused


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
