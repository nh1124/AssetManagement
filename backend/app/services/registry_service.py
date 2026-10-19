from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid
from .money_storage import minor_fields
from .fx_service import convert_amount, get_client_currency
from .product_reserve_service import effective_budget_treatment
from .schedule_rules import occurrences, next_occurrence, count_end_date


SCHEDULE_FIELDS = ("repeat_mode", "frequency", "frequency_days", "day_of_month", "month_of_year", "start_date", "end_date", "repeat_count")
LINE_TYPES = {"income": "income", "expense": "expense", "debt": "debt_payment", "transfer": "allocation"}


def client_today(db: Session, client_id: int) -> date:
    client = db.get(models.Client, client_id)
    zone = (client.general_settings or {}).get("timezone", "UTC") if client else "UTC"
    try:
        target = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        target = timezone.utc
    return datetime.now(timezone.utc).astimezone(target).date()


def validate_account_refs(db: Session, client_id: int, data: dict) -> None:
    for key in ("budget_account_id", "source_account_id", "destination_account_id"):
        account_id = data.get(key)
        if account_id is None:
            continue
        account = db.query(models.Account).filter(
            models.Account.id == account_id, models.Account.client_id == client_id,
        ).first()
        if not account:
            raise Invalid(f"{key} must belong to this client")
    if data.get("source_account_id") == data.get("destination_account_id"):
        raise Invalid("出金元と入金先は別の口座を選んでください")
    if not data.get("source_account_id") or not data.get("destination_account_id"):
        raise Invalid("出金元と入金先を選んでください")


def get_entry(db: Session, client_id: int, entry_id: int) -> models.RegistryEntry | None:
    return db.query(models.RegistryEntry).filter(
        models.RegistryEntry.id == entry_id, models.RegistryEntry.client_id == client_id,
    ).first()


def list_entries(db: Session, client_id: int) -> list[models.RegistryEntry]:
    return db.query(models.RegistryEntry).filter(models.RegistryEntry.client_id == client_id).order_by(
        models.RegistryEntry.kind, models.RegistryEntry.name,
    ).all()


def normalize_schedule(entry) -> None:
    if entry.repeat_mode == "once":
        entry.frequency = entry.frequency_days = entry.day_of_month = entry.month_of_year = None
        entry.repeat_count = entry.end_date = None
    else:
        if entry.frequency not in {"Monthly", "Yearly", "EveryNDays"}:
            raise Invalid("周期を選んでください")
        if entry.frequency == "EveryNDays":
            if not entry.frequency_days or entry.frequency_days < 1:
                raise Invalid("日数は1以上を指定してください")
            entry.day_of_month = entry.month_of_year = None
        else:
            entry.frequency_days = None
            entry.day_of_month = entry.day_of_month or entry.start_date.day
            entry.month_of_year = (entry.month_of_year or entry.start_date.month) if entry.frequency == "Yearly" else None
        if entry.repeat_mode == "count":
            if not entry.repeat_count or entry.repeat_count < 1:
                raise Invalid("回数は1以上を指定してください")
            entry.end_date = count_end_date(entry)
            if entry.end_date is None:
                raise Invalid("回数が日付の範囲を超えています")
        else:
            entry.repeat_count = None
    if entry.end_date and entry.end_date < entry.start_date:
        raise Invalid("終了日は開始日以降にしてください")


def create_entry(db: Session, client_id: int, data: dict, *, today: date | None = None) -> models.RegistryEntry:
    data = {"kind": "expense", "repeat_mode": "indefinite", "budget_active": True, "is_active": True, **data, "currency": data.get("currency") or get_client_currency(db, client_id)}
    validate_account_refs(db, client_id, data)
    entry = models.RegistryEntry(**minor_fields(data, data["currency"], "amount"), client_id=client_id)
    normalize_schedule(entry)
    entry.next_due_date = next_occurrence(entry, today or client_today(db, client_id)) if entry.is_active else None
    db.add(entry)
    db.flush()
    return entry


def update_entry(db: Session, client_id: int, entry_id: int, data: dict, *, today: date | None = None) -> models.RegistryEntry | None:
    entry = get_entry(db, client_id, entry_id)
    if entry is None:
        return None
    merged = {c.name: getattr(entry, c.name) for c in entry.__table__.columns}
    merged.update(data)
    validate_account_refs(db, client_id, merged)
    was_active = entry.is_active
    previous = tuple(getattr(entry, key) for key in SCHEDULE_FIELDS)
    currency = data.get("currency") or entry.currency
    data = {**data, "currency": currency}
    if currency != entry.currency and "amount" not in data:
        data["amount"] = entry.amount
    for key, value in minor_fields(data, currency, "amount").items():
        setattr(entry, key, value)
    normalize_schedule(entry)
    if not entry.is_active:
        entry.next_due_date = None
    elif not was_active or previous != tuple(getattr(entry, key) for key in SCHEDULE_FIELDS):
        entry.next_due_date = next_occurrence(entry, today or client_today(db, client_id))
    db.flush()
    return entry


def delete_entry(db: Session, client_id: int, entry_id: int) -> bool:
    entry = get_entry(db, client_id, entry_id)
    if entry is None:
        return False
    # Preserve journal history on SQLite fixtures as well as PostgreSQL FK actions.
    db.query(models.Transaction).filter(models.Transaction.registry_entry_id == entry.id).update({"registry_entry_id": None})
    db.delete(entry)
    db.flush()
    return True


def product_line_type(product: models.Product) -> str:
    return "allocation" if product.is_asset or effective_budget_treatment(product) in {"reserve_allocation", "asset_replacement"} else "expense"


def product_budget_active(product: models.Product) -> bool:
    return product_line_type(product) == "expense" and bool(product.budget_account_id)


def product_unit_amount(product: models.Product) -> float:
    return (product.last_unit_price or 0) / (product.units_per_purchase or 1)


def registry_entry_amount_for_period(db: Session, entry, period: str, period_start: date, client_id: int, *, budget_only: bool = True) -> float:
    if not entry.is_active or (budget_only and not entry.budget_active):
        return 0.0
    last = period_start.replace(day=calendar.monthrange(period_start.year, period_start.month)[1])
    raw = entry.amount * sum(1 for _ in occurrences(entry, period_start, last))
    return convert_amount(db, client_id, raw, entry.currency, as_of_date=period_start) if raw else 0.0


def registry_target_account_id(entry: models.RegistryEntry) -> int | None:
    return entry.budget_account_id or (entry.source_account_id if entry.kind == "income" else entry.destination_account_id)


def registry_source_account_id(entry: models.RegistryEntry) -> int | None:
    return entry.destination_account_id if entry.kind == "income" else entry.source_account_id


def due_entries(db: Session, client_id: int, today: date) -> list[models.RegistryEntry]:
    return db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == client_id, models.RegistryEntry.is_active.is_(True),
        models.RegistryEntry.next_due_date <= today,
    ).with_for_update(skip_locked=True).all()


def automatic_client_ids(db: Session) -> list[int]:
    return sorted({row[0] for row in db.query(models.RegistryEntry.client_id).filter(models.RegistryEntry.is_active.is_(True))}
                  | {row[0] for row in db.query(models.Product.client_id).filter(models.Product.auto_depreciation.is_(True)) if row[0] is not None})
