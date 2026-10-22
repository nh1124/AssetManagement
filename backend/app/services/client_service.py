from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict

LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


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
    if "password_hash" in fields:
        client.tokens_valid_after = datetime.utcnow()
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


def is_locked(client: models.Client) -> bool:
    return client.locked_until is not None and client.locked_until > datetime.utcnow()


def record_auth_failure(db: Session, client: models.Client) -> None:
    now = datetime.utcnow()
    # Increment in SQL so simultaneous failures cannot overwrite one another.
    count = case(
        (models.Client.locked_until <= now, 1),
        else_=models.Client.failed_login_count + 1,
    )
    db.query(models.Client).filter(models.Client.id == client.id).update({
        models.Client.failed_login_count: count,
        models.Client.locked_until: case(
            (count >= LOCKOUT_THRESHOLD, now + timedelta(minutes=LOCKOUT_MINUTES)),
            else_=None,
        ),
    }, synchronize_session=False)
    db.commit()
    db.refresh(client)


def record_auth_success(db: Session, client: models.Client, *, commit: bool = True) -> None:
    client.failed_login_count = 0
    client.locked_until = None
    if commit:
        db.commit()


def change_password(db: Session, client: models.Client, password_hash: str) -> None:
    client.password_hash = password_hash
    client.must_change_password = False
    client.tokens_valid_after = datetime.utcnow()
    record_auth_success(db, client)


def revoke_tokens(db: Session, client: models.Client, *, commit: bool = True) -> None:
    client.tokens_valid_after = datetime.utcnow()
    if commit:
        db.commit()
