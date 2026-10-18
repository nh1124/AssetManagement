"""Everything that records transactions on its own, in one place.

The registry holds the settings (owner decision U4): a generated definition
posts on its due date, and a product's definition can write its asset down each
period. This workflow runs both and lays them out for the definitions screen,
where whatever waits for a hand is also recorded (U17).
How much a product depreciates stays with the product (U3); this only asks the
depreciation service to post what has fallen due.

Earmark rules also post on their own, but they set money aside from what a
transaction produced rather than record one, so they stay with the earmarks.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from ..domain.errors import Invalid, NotFound
from ..domain.money import Money
from ..services import depreciation_service, product_service, recurring_service, registry_service
from ..services.cache_service import invalidate_client

logger = logging.getLogger(__name__)


def _depreciation_blocked(product) -> str | None:
    if (product.depreciation_method or "none") == "none":
        return "減価の方法が未設定です"
    if not product.depreciation_expense_account_id or not product.depreciation_asset_account_id:
        return "減価の勘定科目（費用・資産）が未設定です"
    if not product.lifespan_months:
        return "耐用月数が未設定です"
    if not (product.depreciation_start_date or product.purchase_date):
        return "購入日または償却開始日が未設定です"
    if not product.purchase_price_minor:
        return "購入価格が未設定です"
    return None


def list_recordings(db: Session, client_id: int, *, today: date | None = None) -> dict:
    """The automatic recordings and their state, without writing anything."""
    effective_today = today or date.today()
    recurring_by_entry = {
        row.source_registry_entry_id: row for row in recurring_service.list_for_client(db, client_id)
    }
    recurring = []
    for entry in registry_service.list_entries(db, client_id):
        if not entry.generate_recurring:
            continue
        row = recurring_by_entry.get(entry.id)
        due = row.next_due_date if row is not None and row.is_active else None
        recurring.append({
            "entry_id": entry.id,
            "entry_type": entry.entry_type,
            "recurring_transaction_id": row.id if row is not None else None,
            "name": entry.name,
            "amount": entry.amount,
            "currency": entry.currency,
            "frequency": entry.frequency,
            "day_of_month": entry.day_of_month,
            "month_of_year": entry.month_of_year,
            "source_account_name": entry.source_account.name if entry.source_account else None,
            "destination_account_name": entry.destination_account.name if entry.destination_account else None,
            "is_active": entry.is_active,
            "auto_post": entry.auto_post,
            "next_due_date": due,
            "is_due": due is not None and due <= effective_today,
        })

    entries = registry_service.product_entries(db, client_id)
    depreciation = []
    for product in sorted(product_service.list_products(db, client_id, is_asset=True), key=lambda row: row.id):
        if (product.depreciation_method or "none") == "none":
            continue
        entry = entries.get(product.id)
        schedule = depreciation_service.schedule(db, client_id, product.id)
        currency = schedule["currency"]
        depreciation.append({
            "product_id": product.id,
            "entry_id": entry.id if entry is not None else None,
            "name": product.name,
            "method": schedule["method"],
            "interval": schedule["interval"],
            "next_period": schedule["next_period"],
            "next_amount": Money(schedule["due_minor"], currency).to_float(),
            "book_value": Money(schedule["book_value_minor"], currency).to_float(),
            "currency": currency,
            "expense_account_id": product.depreciation_expense_account_id,
            "asset_account_id": product.depreciation_asset_account_id,
            "pending_periods":depreciation_service.pending_periods(db, client_id, product, effective_today),
            "auto_depreciation": bool(entry is not None and entry.auto_depreciation),
            "is_active": entry.is_active if entry is not None else True,
            "blocked_reason": _depreciation_blocked(product),
        })
    return {"recurring": recurring, "depreciation": depreciation}


def _post_due_depreciation(db: Session, client_id: int, product_id: int, today: date) -> dict:
    try:
        rows = depreciation_service.post_due(db, client_id, product_id, today=today)
        db.commit()
    except Invalid as error:
        db.rollback()
        return {"product_id": product_id, "periods": [], "skipped": str(error)}
    return {"product_id": product_id, "periods": [row.period for row in rows], "skipped": None}


def process_due(db: Session, client_id: int, *, today: date | None = None) -> dict:
    """Post every automatic recording that has fallen due for one client."""
    effective_today = today or date.today()
    recurring = recurring_service.process_due_for_client(db, client_id, today=effective_today)
    depreciation = [
        _post_due_depreciation(db, client_id, entry.source_product_id, effective_today)
        for entry in registry_service.auto_depreciation_entries(db, client_id)
    ]
    if any(item["periods"] for item in depreciation):
        invalidate_client(client_id)
    return {"recurring": recurring, "depreciation": [item for item in depreciation if item["periods"] or item["skipped"]]}


def process_due_all(db: Session, *, today: date | None = None) -> None:
    """The daily run: every client with something due, one failure at a time."""
    effective_today = today or date.today()
    clients = recurring_service.clients_with_due_auto_post(db, effective_today)
    clients |= registry_service.clients_with_auto_depreciation(db)
    for client_id in sorted(clients):
        try:
            process_due(db, client_id, today=effective_today)
        except Exception:
            db.rollback()
            logger.exception("Automatic recording failed for client_id=%s", client_id)


def post_due_depreciation(db: Session, client_id: int, product_id: int, *, today: date | None = None) -> dict:
    """Write down by hand the ended periods not yet recorded, oldest first (U17)."""
    product = product_service.get_product(db, client_id, product_id)
    if product is None:
        raise NotFound("物品が見つかりません")
    reason = _depreciation_blocked(product) if product.is_asset else "減価を記帳できるのは固定資産だけです"
    if reason:
        raise Invalid(reason)
    try:
        rows = depreciation_service.post_due(db, client_id, product_id, today=today or date.today())
        if not rows:
            raise Invalid("記帳する期はまだありません")
        db.commit()
    except Exception:
        db.rollback()
        raise
    invalidate_client(client_id)
    return {"product_id": product_id, "posted_periods": [row.period for row in rows]}


def set_auto_depreciation(
    db: Session, client_id: int, product_id: int, *, enabled: bool, today: date | None = None,
) -> dict:
    """Switch a product's automatic write-down; switching on posts what is due now."""
    product = product_service.get_product(db, client_id, product_id)
    if product is None:
        raise NotFound("物品が見つかりません")
    if enabled:
        if not product.is_asset:
            raise Invalid("減価を記帳できるのは固定資産だけです")
        reason = _depreciation_blocked(product)
        if reason:
            raise Invalid(reason)
    registry_service.set_auto_depreciation(db, product, enabled)
    db.commit()
    posted: list[str] = []
    skipped = None
    if enabled:
        result = _post_due_depreciation(db, client_id, product_id, today or date.today())
        posted, skipped = result["periods"], result["skipped"]
    invalidate_client(client_id)
    return {"product_id": product_id, "auto_depreciation": enabled, "posted_periods": posted, "skipped": skipped}
