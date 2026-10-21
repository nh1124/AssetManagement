"""Posting primitives and read models for automatic recordings; never commits."""
from __future__ import annotations

from datetime import date, timedelta
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..domain.money import Money
from ..domain.errors import Invalid
from . import depreciation_service, ledger_service, product_service, registry_service
from .capsule_service import apply_capsule_rules_for_transaction
from .fx_service import get_client_currency, convert_amount
from .periods import period_to_range
from .schedule_rules import occurrences, next_occurrence


def post_due(db: Session, client_id: int, today: date) -> list[dict]:
    processed = []
    for entry in registry_service.due_entries(db, client_id, today):
        ids = []
        handled = 0
        for due in occurrences(entry, entry.next_due_date, today):
            # Goal reflection may set the monthly saving to zero. The date still advances.
            existing = db.query(models.Transaction.id).filter(
                models.Transaction.client_id == client_id, models.Transaction.registry_entry_id == entry.id,
                models.Transaction.date == due,
            ).first()
            if entry.amount_minor > 0 and not existing:
                transaction = ledger_service.create_transaction(
                    db, client_id=client_id, registry_entry_id=entry.id, date=due,
                    description=entry.name, amount_minor=entry.amount_minor, currency=entry.currency,
                    from_account_id=entry.source_account_id, to_account_id=entry.destination_account_id,
                )
                apply_capsule_rules_for_transaction(db, transaction, commit=False)
                ids.append(transaction.id)
            entry.next_due_date = next_occurrence(entry, due + timedelta(days=1)) if due < date.max else None
            handled += 1
            if handled == 24:
                break
        # A migrated cursor can be beyond the optional end date.
        if not handled:
            entry.next_due_date = None
        if ids:
            processed.append({"entry_id": entry.id, "transaction_ids": ids, "next_due_date": entry.next_due_date})
    db.flush()
    return processed


def depreciation_listing(db: Session, client_id: int) -> list[dict]:
    rows = []
    for product in product_service.list_products(db, client_id, is_asset=True):
        if product.depreciation_method == "none":
            continue
        schedule = depreciation_service.schedule(db, client_id, product.id)
        currency = schedule["currency"]
        rows.append({
            "product_id": product.id, "name": product.name, "method": schedule["method"],
            "interval": schedule["interval"], "next_period": schedule["next_period"],
            "next_amount": Money(schedule["due_minor"], currency).to_float(),
            "book_value": Money(schedule["book_value_minor"], currency).to_float(),
            "currency": currency, "auto_depreciation": product.auto_depreciation,
        })
    return rows


def scheduled_in_period(db: Session, client_id: int, period: str) -> dict:
    start, end = _period_range(period)
    items = []
    for entry in registry_service.list_entries(db, client_id):
        if not entry.is_active:
            continue
        for due in occurrences(entry, start, end - timedelta(days=1)):
            items.append({
                "kind": "automatic_transaction", "entry_id": entry.id, "product_id": None,
                "name": entry.name, "line_type": registry_service.LINE_TYPES[entry.kind],
                "amount": convert_amount(db, client_id, entry.amount, entry.currency, as_of_date=start), "date": due, "frequency": entry.frequency,
                "posted": bool(db.query(models.Transaction.id).filter(
                    models.Transaction.client_id == client_id, models.Transaction.registry_entry_id == entry.id,
                    models.Transaction.date == due,
                ).first()), "in_budget": entry.budget_active, "records_transactions": entry.records_transactions,
                "account_id": registry_service.registry_target_account_id(entry),
                "counter_account_id": registry_service.registry_source_account_id(entry),
            })
    for product in product_service.list_products(db, client_id, is_asset=True):
        if not product.auto_depreciation:
            continue
        found = depreciation_service.period_amount(db, client_id, product, period)
        if found is None:
            continue
        minor, posted = found
        items.append({"kind": "depreciation", "entry_id": None, "product_id": product.id,
                      "name": product.name, "line_type": None, "amount": Money(minor, get_client_currency(db, client_id)).to_float(),
                      "date": end - timedelta(days=1), "frequency": product.depreciation_interval,
                      "posted": posted, "in_budget": False, "records_transactions": True, "account_id": product.depreciation_expense_account_id,
                      "counter_account_id": product.depreciation_asset_account_id})
    items.sort(key=lambda row: (row["date"], row["name"]))
    return {"period": period, "currency": get_client_currency(db, client_id), "items": items}


def generated_in_period(db: Session, client_id: int, period: str) -> list[dict]:
    start, end = _period_range(period)
    depreciation_ids = db.query(models.ProductDepreciation.transaction_id).filter(models.ProductDepreciation.client_id == client_id)
    rule_transaction_ids = db.query(models.TransactionProposal.posted_transaction_id).filter(
        models.TransactionProposal.client_id == client_id, models.TransactionProposal.origin == "capsule",
        models.TransactionProposal.posted_transaction_id.isnot(None),
    )
    rows = db.query(models.Transaction).filter(
        models.Transaction.client_id == client_id, models.Transaction.date >= start, models.Transaction.date < end,
        or_(models.Transaction.registry_entry_id.isnot(None), models.Transaction.id.in_(depreciation_ids), models.Transaction.id.in_(rule_transaction_ids)),
    ).order_by(models.Transaction.date, models.Transaction.id).all()
    depreciation = {row[0] for row in depreciation_ids}
    return [{"id": row.id, "date": row.date, "description": row.description, "amount": row.amount,
             "currency": row.currency, "source": row.registry_entry.name if row.registry_entry is not None else
             ("固定資産の減価" if row.id in depreciation else "取り置きの規則")} for row in rows]


def _period_range(period: str):
    try:
        return period_to_range(period)
    except (ValueError, TypeError, AttributeError) as error:
        raise Invalid("期間はYYYY-MMで指定してください") from error
