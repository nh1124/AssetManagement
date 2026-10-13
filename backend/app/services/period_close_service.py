"""Monthly review markers, independent of journal posting and planning."""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid, NotFound


def validate_period(period: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", period):
        raise Invalid("期間は YYYY-MM 形式で指定してください。")
    try:
        date(int(period[:4]), int(period[5:]), 1)
    except ValueError as exc:
        raise Invalid("期間は YYYY-MM 形式の有効な年月で指定してください。") from exc
    return period


def _get_close(db: Session, client_id: int, period: str) -> models.PeriodClose | None:
    return db.query(models.PeriodClose).filter_by(client_id=client_id, period=validate_period(period)).first()


def close_period(db: Session, client_id: int, period: str, *, note: str | None = None) -> models.PeriodClose:
    validate_period(period)
    # Serialize repeated closes on the owner so the unique key remains idempotent.
    client = db.query(models.Client).filter_by(id=client_id).with_for_update().first()
    if client is None:
        raise NotFound("Client not found")
    row = _get_close(db, client_id, period)
    if row is None:
        row = models.PeriodClose(client_id=client_id, period=period, closed_at=datetime.utcnow(), note=note)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def reopen_period(db: Session, client_id: int, period: str) -> None:
    row = _get_close(db, client_id, period)
    if row is not None:
        db.delete(row)
    db.commit()


def list_closes(db: Session, client_id: int) -> list[models.PeriodClose]:
    return db.query(models.PeriodClose).filter_by(client_id=client_id).order_by(
        models.PeriodClose.period.desc(), models.PeriodClose.id.desc(),
    ).all()


def is_closed(db: Session, client_id: int, period: str) -> bool:
    return _get_close(db, client_id, period) is not None
