from decimal import Decimal
from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from ..models.money import settings_currency


def money_client_currency(db: Session, client_id: int | None) -> str:
    if client_id is None:
        raise ValueError("Cannot resolve client currency without a client_id")
    client = next((row for row in db.new if isinstance(row, models.Client) and row.id == client_id), None)
    if client is None and client_id is not None:
        client = db.get(models.Client, client_id)
    if client is None:
        raise ValueError(f"Cannot resolve client currency for client {client_id}")
    return settings_currency(client.general_settings)


def to_minor(value, currency: str) -> int | None:
    return None if value is None else Money.from_major(str(value), currency).minor


def minor_fields(data: dict, currency: str, *names: str) -> dict:
    result = dict(data)
    for name in names:
        if name in result:
            result[f"{name}_minor"] = to_minor(result.pop(name), currency)
    return result


def rule_amount_fields(value, amount_type: str, currency: str) -> dict:
    if amount_type == "fixed":
        return {"amount_minor": to_minor(value, currency), "percentage_bp": None}
    if amount_type == "percentage":
        bp = Decimal(str(value)) * 100
        if not bp.is_finite() or bp != bp.to_integral_value():
            raise ValueError("Percentage must be exact in basis points")
        return {"amount_minor": None, "percentage_bp": int(bp)}
    raise ValueError(f"Unsupported capsule rule amount_type {amount_type!r}")


def rule_data(data: dict, currency: str) -> dict:
    result = dict(data)
    result.update(rule_amount_fields(result.pop("amount_value", 0), result.get("amount_type", "fixed"), currency))
    return result
