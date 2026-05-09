from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .. import models
from .fx_service import convert_amount
from .product_reserve_service import effective_budget_treatment


OUTFLOW_TRANSACTION_TYPES = {"Expense", "CreditExpense", "Transfer", "CreditAssetPurchase", "LiabilityPayment"}


def recurring_line_type(tx_type: str | None) -> str:
    kind = tx_type or "Expense"
    if kind == "Income":
        return "income"
    if kind == "Borrowing":
        return "borrowing"
    if kind in {"Transfer", "CreditAssetPurchase"}:
        return "allocation"
    if kind == "LiabilityPayment":
        return "debt_payment"
    return "expense"


def recurring_entry_type(tx_type: str | None) -> str:
    kind = tx_type or "Expense"
    if kind == "Income":
        return "income"
    if kind == "LiabilityPayment":
        return "debt"
    if kind in {"Transfer", "CreditAssetPurchase"}:
        return "allocation"
    return "service"


def product_line_type(product: models.Product) -> str:
    treatment = effective_budget_treatment(product)
    if product.is_asset or treatment in {"reserve_allocation", "asset_replacement"}:
        return "allocation"
    return "expense"


def product_budget_active(product: models.Product) -> bool:
    return product_line_type(product) == "expense" and bool(product.budget_account_id)


def product_unit_amount(product: models.Product) -> float:
    units = product.units_per_purchase or 1
    return (product.last_unit_price or 0.0) / units if units else (product.last_unit_price or 0.0)


def sync_registry_from_product(db: Session, product: models.Product) -> models.RegistryEntry:
    entry = db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == product.client_id,
        models.RegistryEntry.source_product_id == product.id,
    ).first()
    if not entry:
        entry = models.RegistryEntry(client_id=product.client_id, source_product_id=product.id)
        db.add(entry)

    entry.name = product.name
    entry.entry_type = "asset" if product.is_asset else "item"
    entry.category = product.budget_account.name if product.budget_account else product.category
    entry.amount = product_unit_amount(product)
    entry.currency = "JPY"
    entry.frequency = "EveryNDays" if product.frequency_days and product.frequency_days > 0 else "Irregular"
    entry.frequency_days = product.frequency_days or None
    entry.transaction_type = "Expense"
    entry.line_type = product_line_type(product)
    entry.budget_account_id = product.budget_account_id
    entry.funding_capsule_id = product.funding_capsule_id
    entry.budget_treatment = product.budget_treatment or "auto"
    entry.generate_recurring = False
    entry.budget_active = product_budget_active(product)
    entry.is_active = True
    return entry


def sync_registry_from_recurring(db: Session, recurring: models.RecurringTransaction) -> models.RegistryEntry:
    entry = None
    if recurring.source_registry_entry_id:
        entry = db.query(models.RegistryEntry).filter(
            models.RegistryEntry.id == recurring.source_registry_entry_id,
            models.RegistryEntry.client_id == recurring.client_id,
        ).first()
    if not entry:
        entry = db.query(models.RegistryEntry).filter(
            models.RegistryEntry.client_id == recurring.client_id,
            models.RegistryEntry.source_recurring_transaction_id == recurring.id,
        ).first()
    if not entry:
        entry = models.RegistryEntry(client_id=recurring.client_id)
        db.add(entry)

    line_type = recurring_line_type(recurring.type)
    entry.name = recurring.name
    entry.entry_type = recurring_entry_type(recurring.type)
    entry.amount = recurring.amount or 0.0
    entry.currency = recurring.currency or "JPY"
    entry.frequency = recurring.frequency or "Monthly"
    entry.frequency_days = None
    entry.day_of_month = recurring.day_of_month or 1
    entry.month_of_year = recurring.month_of_year
    entry.transaction_type = recurring.type or "Expense"
    entry.line_type = line_type
    entry.budget_account_id = recurring.to_account_id if line_type in {"expense", "debt_payment"} else None
    entry.source_account_id = recurring.from_account_id
    entry.destination_account_id = recurring.to_account_id
    entry.generate_recurring = True
    entry.budget_active = True
    entry.is_active = bool(recurring.is_active)
    entry.source_recurring_transaction_id = recurring.id
    entry.start_period = recurring.start_period
    entry.end_period = recurring.end_period
    recurring.source_registry_entry = entry
    return entry


def detach_registry_from_recurring(db: Session, recurring: models.RecurringTransaction) -> None:
    entry = None
    if recurring.source_registry_entry_id:
        entry = db.query(models.RegistryEntry).filter(
            models.RegistryEntry.id == recurring.source_registry_entry_id,
            models.RegistryEntry.client_id == recurring.client_id,
        ).first()
    if not entry:
        entry = db.query(models.RegistryEntry).filter(
            models.RegistryEntry.client_id == recurring.client_id,
            models.RegistryEntry.source_recurring_transaction_id == recurring.id,
        ).first()
    if entry:
        entry.generate_recurring = False
        entry.source_recurring_transaction_id = None
    recurring.source_registry_entry_id = None


def ensure_registry_entries(db: Session, client_id: int) -> None:
    changed = False
    products = db.query(models.Product).filter(models.Product.client_id == client_id).all()
    for product in products:
        if not db.query(models.RegistryEntry).filter(
            models.RegistryEntry.client_id == client_id,
            models.RegistryEntry.source_product_id == product.id,
        ).first():
            sync_registry_from_product(db, product)
            changed = True

    recurring_rows = db.query(models.RecurringTransaction).filter(models.RecurringTransaction.client_id == client_id).all()
    for recurring in recurring_rows:
        if not recurring.source_registry_entry_id and not db.query(models.RegistryEntry).filter(
            models.RegistryEntry.client_id == client_id,
            models.RegistryEntry.source_recurring_transaction_id == recurring.id,
        ).first():
            sync_registry_from_recurring(db, recurring)
            changed = True

    if changed:
        db.commit()


def registry_entry_amount_for_period(
    db: Session,
    entry: models.RegistryEntry,
    period: str,
    period_start: date,
    client_id: int,
) -> float:
    if not entry.is_active or not entry.budget_active:
        return 0.0
    if entry.start_period and period < entry.start_period:
        return 0.0
    if entry.end_period and period > entry.end_period:
        return 0.0

    frequency = entry.frequency or "Monthly"
    amount = entry.amount or 0.0
    if frequency == "Monthly":
        raw = amount
    elif frequency == "Yearly":
        raw = amount if (entry.month_of_year or period_start.month) == period_start.month else 0.0
    elif frequency == "EveryNDays":
        raw = amount * (30 / entry.frequency_days) if entry.frequency_days and entry.frequency_days > 0 else 0.0
    else:
        raw = 0.0
    if raw <= 0:
        return 0.0
    return convert_amount(db, client_id, raw, entry.currency, as_of_date=period_start)


def registry_target_account_id(entry: models.RegistryEntry) -> int | None:
    if entry.line_type in {"income", "borrowing", "drawdown"}:
        return entry.source_account_id or entry.destination_account_id
    return entry.budget_account_id or entry.destination_account_id


def registry_source_account_id(entry: models.RegistryEntry) -> int | None:
    if entry.line_type in {"income", "borrowing", "drawdown"}:
        return entry.destination_account_id
    return entry.source_account_id
