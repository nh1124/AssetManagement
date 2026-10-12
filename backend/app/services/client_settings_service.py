from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import models, security
from ..domain.errors import Invalid
from ..domain.money import normalize_currency


def set_gemini_api_key(
    db: Session, client: models.Client, raw_key: str, *, commit: bool = True,
) -> None:
    config = dict(client.ai_config) if client.ai_config else {}
    config["gemini_api_key"] = security.encrypt_key(raw_key)
    client.ai_config = config
    # SQLAlchemy does not detect mutated JSON columns without an explicit dirty flag.
    flag_modified(client, "ai_config")
    if commit:
        db.commit()
    else:
        db.flush()


def merge_general_settings(
    db: Session, client: models.Client, patch: dict, *, commit: bool = True,
) -> dict:
    settings = dict(client.general_settings or {})
    settings.update(patch or {})
    if "currency" in settings:
        # X11: every money column in the schema is denominated by this one
        # setting, so an unsupported code here is refused where it is set
        # rather than discovered by the next read that tries to use it.
        try:
            settings["currency"] = normalize_currency(settings["currency"])
        except ValueError as exc:
            raise Invalid(str(exc)) from exc
    client.general_settings = settings
    # SQLAlchemy does not detect mutated JSON columns without an explicit dirty flag.
    flag_modified(client, "general_settings")
    if commit:
        db.commit()
    else:
        db.flush()
    return client.general_settings


def merge_ai_execution_settings(
    db: Session, client: models.Client, patch: dict, *, commit: bool = True,
) -> dict:
    settings = dict(client.general_settings or {})
    ai_operation = dict(settings.get("ai_operation") or {})
    ai_operation.update(patch)
    settings["ai_operation"] = ai_operation
    client.general_settings = settings
    # SQLAlchemy does not detect mutated JSON columns without an explicit dirty flag.
    flag_modified(client, "general_settings")
    if commit:
        db.commit()
        db.refresh(client)
    else:
        db.flush()
    return client.general_settings["ai_operation"]
