from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import models
from ..domain.errors import Invalid
from ..domain.money import normalize_currency





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


# 計画への反映 (WP27): how the goal and the product earmarks are written into the plan, and whether
# that happens by itself at the start of a month and after a change.
REFLECTION_DEFAULTS = {
    "enabled": False,
    "goal": {"base": "remaining", "held": "even", "catch_up": "even"},
    "products": {"enabled": True, "base": "remaining", "held": "even"},
    "since": None,
    "last_period": None,
}
REFLECTION_CHOICES = {
    ("goal", "base"): ("remaining", "goal_setting"),
    ("goal", "held"): ("even", "recent"),
    ("goal", "catch_up"): ("even", "recent", "none"),
    ("products", "base"): ("remaining", "saved"),
    ("products", "held"): ("even", "recent"),
}


def reflection_settings(client: models.Client) -> dict:
    """The stored settings over the defaults."""
    stored = dict((client.general_settings or {}).get("plan_reflection") or {})
    return {
        "enabled": bool(stored.get("enabled", REFLECTION_DEFAULTS["enabled"])),
        "goal": {**REFLECTION_DEFAULTS["goal"], **(stored.get("goal") or {})},
        "products": {**REFLECTION_DEFAULTS["products"], **(stored.get("products") or {})},
        "since": stored.get("since"),
        "last_period": stored.get("last_period"),
    }


def merge_reflection_settings(
    db: Session, client: models.Client, patch: dict, *, period: str, commit: bool = True,
) -> dict:
    """Save a change of the settings. `since` (from when a shortfall counts) is the month they were first saved."""
    current = reflection_settings(client)
    for group in ("goal", "products"):
        for key, value in (patch.get(group) or {}).items():
            if key == "enabled" and group == "products":
                current[group][key] = bool(value)
                continue
            choices = REFLECTION_CHOICES.get((group, key))
            if choices is None or value not in choices:
                raise Invalid(f"反映の設定 {group}.{key} の値が不正です。")
            current[group][key] = value
    if "enabled" in patch:
        current["enabled"] = bool(patch["enabled"])
    for key in ("last_period",):
        if key in patch:
            current[key] = patch[key]
    current["since"] = current["since"] or period
    settings = dict(client.general_settings or {})
    settings["plan_reflection"] = current
    client.general_settings = settings
    flag_modified(client, "general_settings")
    if commit:
        db.commit()
    else:
        db.flush()
    return current


def reflection_client_ids(db: Session) -> list[int]:
    """The active clients whose 自動反映 is on, for the start-of-month run."""
    return [client.id for client in db.query(models.Client).filter(models.Client.is_active.is_(True)).order_by(models.Client.id)
            if reflection_settings(client)["enabled"]]

