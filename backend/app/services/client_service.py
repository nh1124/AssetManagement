from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict


def get_by_username(
    db: Session, username: str, *, active_only: bool = False,
) -> models.Client | None:
    query = db.query(models.Client).filter(models.Client.username == username)
    if active_only:
        query = query.filter(models.Client.is_active == True)
    return query.first()


def get_by_email(db: Session, email: str) -> models.Client | None:
    return db.query(models.Client).filter(models.Client.email == email).first()


def get_active_by_id(db: Session, client_id: int) -> models.Client | None:
    return db.query(models.Client).filter(
        models.Client.id == client_id,
        models.Client.is_active == True,
    ).first()


def unique_display_name(db: Session, base_name: str) -> str:
    seed = (base_name or "user").strip() or "user"
    candidate = seed
    suffix = 2
    # Selection does not reserve the name; the unique constraint catches races
    # when registration commits, without retrying the losing registration.
    while db.query(models.Client).filter(models.Client.name == candidate).first():
        candidate = f"{seed}-{suffix}"
        suffix += 1
    return candidate


def register(
    db: Session, *, name: str, username: str, email: str | None,
    password_hash: str,
) -> models.Client:
    client = models.Client(
        name=name,
        username=username,
        email=email,
        password_hash=password_hash,
        general_settings={},
    )
    try:
        db.add(client)
        db.commit()
        db.refresh(client)
    except IntegrityError:
        db.rollback()
        raise
    return client


def update_profile(
    db: Session, client: models.Client, fields: dict, *, commit: bool = True,
) -> models.Client:
    for key in ("name", "email", "password_hash"):
        if key in fields:
            setattr(client, key, fields[key])
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        # Names and emails are unique across clients.
        db.rollback()
        raise Conflict("この名前またはメールアドレスは使われています。", en="This name or email is already in use.") from exc
    return client
