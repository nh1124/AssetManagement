from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Conflict, Invalid, NotFound
from ..utils.password import hash_password
from ..utils.temporary_password import temporary_password
from . import system_settings_service, mfa_service



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
    password_hash: str, approval_pending: bool = False, commit: bool = True,
) -> models.Client:
    client = models.Client(
        name=name,
        username=username,
        email=email,
        password_hash=password_hash,
        general_settings={}, approval_pending=approval_pending,
    )
    try:
        db.add(client)
        db.commit() if commit else db.flush()
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
    threshold = system_settings_service.get(db, "login_lockout_threshold")
    minutes = system_settings_service.get(db, "login_lockout_minutes")
    # Increment in SQL so simultaneous failures cannot overwrite one another.
    count = case(
        (models.Client.locked_until <= now, 1),
        else_=models.Client.failed_login_count + 1,
    )
    db.query(models.Client).filter(models.Client.id == client.id).update({
        models.Client.failed_login_count: count,
        models.Client.locked_until: case(
            (count >= threshold, now + timedelta(minutes=minutes)),
            else_=None,
        ),
    }, synchronize_session=False)
    db.commit()
    db.refresh(client)


def record_auth_success(db: Session, client: models.Client, *, commit: bool = True) -> None:
    db.flush()
    db.query(models.Client).filter(
        models.Client.id == client.id,
        or_(models.Client.locked_until.is_(None), models.Client.locked_until <= datetime.utcnow()),
    ).update({models.Client.failed_login_count: 0, models.Client.locked_until: None}, synchronize_session=False)
    if commit:
        db.commit()
    db.refresh(client)


def change_password(db: Session, client: models.Client, password_hash: str) -> None:
    client.password_hash = password_hash
    client.must_change_password = False
    client.tokens_valid_after = datetime.utcnow()
    db.commit()


def revoke_tokens(db: Session, client: models.Client, *, commit: bool = True) -> None:
    client.tokens_valid_after = datetime.utcnow()
    if commit:
        db.commit()


def get_by_id(db: Session, client_id: int) -> models.Client:
    client = db.get(models.Client, client_id)
    if client is None:
        raise NotFound("Client not found", ja="クライアントが見つかりません。")
    return client


def _save(db: Session, client: models.Client, commit: bool):
    db.commit() if commit else db.flush()
    return client


def create_by_admin(db: Session, username: str, name: str, email: str | None = None, *, commit: bool = True):
    username = username.strip().lower()
    if not username or not name.strip():
        raise Invalid("Username and name are required.", ja="ユーザー名と名前を入力してください。")
    password = temporary_password()
    client = register(db, username=username, name=unique_display_name(db, name),
                      email=email.strip().lower() if email else None,
                      password_hash=hash_password(password), commit=False)
    client.must_change_password = True
    _save(db, client, commit)
    return client, password


def suspend(db: Session, client: models.Client, reason: str, *, commit: bool = True):
    if not reason.strip():
        raise Invalid("A suspension reason is required.", ja="停止理由を入力してください。")
    client.is_active, client.suspended_reason = False, reason
    client.tokens_valid_after = datetime.utcnow()
    return _save(db, client, commit)


def reactivate(db: Session, client: models.Client, *, commit: bool = True):
    client.is_active, client.suspended_reason = True, None
    return _save(db, client, commit)


def approve(db: Session, client: models.Client, *, commit: bool = True):
    client.approval_pending = False
    return _save(db, client, commit)


def unlock(db: Session, client: models.Client, *, commit: bool = True):
    client.failed_login_count, client.locked_until = 0, None
    return _save(db, client, commit)


def sign_out(db: Session, client: models.Client, *, commit: bool = True):
    revoke_tokens(db, client, commit=commit)
    return client


def reset_password(db: Session, client: models.Client, *, commit: bool = True) -> str:
    password = temporary_password()
    client.password_hash = hash_password(password)
    client.must_change_password = True
    client.tokens_valid_after = datetime.utcnow()
    _save(db, client, commit)
    return password


def _admin_attributes(client, count, last_date, enabled):
    return {"id": client.id, **{key: getattr(client, key) for key in (
        "username", "name", "email", "is_active", "approval_pending", "suspended_reason",
        "must_change_password", "locked_until", "created_at")},
        "mfa_enabled": enabled, "transaction_count": count, "last_transaction_date": last_date}


def _transaction_counts(db: Session, client_ids):
    return {client_id: (count, last_date) for client_id, count, last_date in db.query(
        models.Transaction.client_id, func.count(models.Transaction.id), func.max(models.Transaction.date),
    ).filter(models.Transaction.client_id.in_(client_ids)).group_by(models.Transaction.client_id).all()}


def admin_summary(db: Session, client: models.Client) -> dict:
    count, last_date = _transaction_counts(db, [client.id]).get(client.id, (0, None))
    return _admin_attributes(client, count, last_date, mfa_service.mfa_enabled(db, client.id))


def admin_list(db: Session, *, status=None, query=None, limit: int = 100, offset: int = 0) -> list[dict]:
    if not 1 <= limit <= 1000 or offset < 0:
        raise Invalid("Invalid pagination.", ja="ページの指定が正しくありません。")
    rows = db.query(models.Client)
    if status == "active":
        rows = rows.filter(models.Client.is_active.is_(True), models.Client.approval_pending.is_(False))
    elif status == "suspended":
        rows = rows.filter(models.Client.is_active.is_(False))
    elif status == "pending":
        rows = rows.filter(models.Client.approval_pending.is_(True))
    elif status == "locked":
        rows = rows.filter(models.Client.locked_until > datetime.utcnow())
    elif status is not None:
        raise Invalid("Unknown account status.", ja="不明なアカウント状態です。")
    if query:
        rows = rows.filter(or_(*(getattr(models.Client, key).icontains(query, autoescape=True)
                                for key in ("username", "name", "email"))))
    clients = rows.order_by(models.Client.id).limit(limit).offset(offset).all()
    ids = [client.id for client in clients]
    if not ids:
        return []
    counts = _transaction_counts(db, ids)
    enabled = {row[0] for row in db.query(models.ClientMfaSetting.client_id).filter(
        models.ClientMfaSetting.client_id.in_(ids), models.ClientMfaSetting.enabled.is_(True)).all()}
    return [_admin_attributes(client, *counts.get(client.id, (0, None)), client.id in enabled) for client in clients]


def admin_client_ids(db: Session) -> list[int]:
    """Health inspection includes suspended and pending accounts."""
    return [row[0] for row in db.query(models.Client.id).order_by(models.Client.id).all()]
