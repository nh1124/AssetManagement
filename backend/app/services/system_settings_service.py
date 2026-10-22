"""Owns installation settings and their typed defaults."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid


@dataclass(frozen=True)
class Definition:
    default: str | int
    choices: frozenset[str] | None = None
    minimum: int | None = None
    maximum: int | None = None

    def accepts(self, value) -> bool:
        if self.choices is not None:
            return type(value) is str and value in self.choices
        return type(value) is int and self.minimum <= value <= self.maximum


DEFINITIONS = {
    "registration_mode": Definition("open", choices=frozenset({"open", "approval", "closed"})),
    "account_deletion_grace_days": Definition(30, minimum=1, maximum=365),
    "login_lockout_threshold": Definition(5, minimum=3, maximum=20),
    "login_lockout_minutes": Definition(15, minimum=1, maximum=1440),
}


def _definition(key: str) -> Definition:
    if key not in DEFINITIONS:
        raise Invalid("Unknown system setting.", ja="不明なシステム設定です。")
    return DEFINITIONS[key]


def get(db: Session, key: str):
    definition = _definition(key)
    row = db.get(models.SystemSetting, key)
    return row.value if row is not None else definition.default


def all(db: Session) -> dict:
    rows = {row.key: row for row in db.query(models.SystemSetting).all()}
    return {key: {"value": rows[key].value if key in rows else definition.default,
                  "default": definition.default,
                  "updated_at": rows[key].updated_at if key in rows else None,
                  "updated_by": rows[key].updated_by if key in rows else None}
            for key, definition in DEFINITIONS.items()}


def set(db: Session, key: str, value, actor: str, *, commit: bool = True):
    if not _definition(key).accepts(value):
        raise Invalid("Invalid system setting value.", ja="システム設定の値が正しくありません。")
    row = db.get(models.SystemSetting, key)
    if row is None:
        row = models.SystemSetting(key=key)
        db.add(row)
    row.value, row.updated_at, row.updated_by = value, datetime.utcnow(), actor
    db.commit() if commit else db.flush()
    return value
