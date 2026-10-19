"""Writing a fixed asset down in the journal rather than only in a report.

The direct method: the expense account is debited and the item account credited,
so the asset's carrying amount falls with every posting. Nothing here keeps a
running total -- the book value is the purchase price less the sum of the posted
rows, so the figure and the entries that produced it cannot drift apart.

Layer 1: this builds on the ledger and on period arithmetic, and on nothing else.
"""
from __future__ import annotations

from datetime import date as Date

from dateutil.relativedelta import relativedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Invalid
from ..domain.journal import Leg
from ..domain.money import Money
from . import ledger_service
from .fx_service import get_client_currency
from .periods import period_to_range

METHODS = ("none", "straight_line", "declining_balance")
INTERVALS = ("monthly", "yearly")


def _period_key(value: Date) -> str:
    return f"{value.year}-{value.month:02d}"


def _validate_period(period: str) -> Date:
    try:
        start, _ = period_to_range(period)
    except (ValueError, AttributeError) as error:
        raise Invalid("Period must be YYYY-MM") from error
    return start


def _get_product(db: Session, client_id: int, product_id: int) -> models.Product:
    product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.client_id == client_id,
    ).first()
    if product is None:
        raise Invalid("Product not found for this client")
    return product


def posted_minor(db: Session, client_id: int, product_id: int) -> int:
    total = db.query(func.coalesce(func.sum(models.ProductDepreciation.amount_minor), 0)).filter(
        models.ProductDepreciation.client_id == client_id,
        models.ProductDepreciation.product_id == product_id,
    ).scalar()
    return int(total or 0)


def _start_date(product: models.Product) -> Date | None:
    return product.depreciation_start_date or product.purchase_date


def _months_in(interval: str) -> int:
    return 12 if interval == "yearly" else 1


def _next_period(db: Session, client_id: int, product: models.Product) -> str | None:
    """The first period at or after the start that has not been posted.

    Stepping by the interval rather than by month, so a yearly schedule does not
    silently become twelve monthly ones.
    """
    start = _start_date(product)
    if start is None:
        return None
    posted = {row.period for row in db.query(models.ProductDepreciation.period).filter(
        models.ProductDepreciation.client_id == client_id,
        models.ProductDepreciation.product_id == product.id,
    )}
    step = _months_in(product.depreciation_interval or "monthly")
    cursor = start.replace(day=1)
    # Bounded: a life longer than a century is not a schedule, it is a mistake.
    for _ in range(1200 // step + 1):
        key = _period_key(cursor)
        if key not in posted:
            return key
        cursor += relativedelta(months=step)
    return None


def _posting_date(period: str) -> Date:
    """A period is written down on its last day."""
    _, end = period_to_range(period)
    return end - relativedelta(days=1)


def _months_elapsed(start: Date, period: str) -> int:
    begins = start.replace(day=1)
    at, _ = period_to_range(period)
    return (at.year - begins.year) * 12 + (at.month - begins.month)


def due_minor(db: Session, client_id: int, product: models.Product, period: str) -> int:
    """What this period writes down, never more than the value that is left."""
    currency = get_client_currency(db, client_id)
    price = int(product.purchase_price_minor or 0)
    remaining = price - posted_minor(db, client_id, product.id)
    if remaining <= 0:
        return 0

    life = int(product.lifespan_months or 0)
    if life <= 0:
        raise Invalid("Depreciation needs a lifespan in months")
    start = _start_date(product)
    if start is None:
        raise Invalid("Set a purchase date or a depreciation start date first")

    months = _months_in(product.depreciation_interval or "monthly")
    method = product.depreciation_method or "none"
    if method == "straight_line":
        amount = Money(price, currency).allocate([1] * life)[0].minor * months
    elif method == "declining_balance":
        rate = float(product.depreciation_annual_rate or 0.0)
        if rate <= 0:
            raise Invalid("Declining-balance depreciation needs an annual rate above zero")
        amount = int(remaining * rate / 100.0 / 12.0 * months)
    else:
        raise Invalid("This product has no depreciation method")

    # A declining balance never reaches zero by arithmetic, so the useful life is
    # what ends it: the posting that reaches the end of the life takes whatever
    # is left. The same rule gives a straight line an exact last instalment when
    # the price does not divide evenly.
    if _months_elapsed(start, period) + months >= life or amount <= 0:
        return remaining
    return min(amount, remaining)


def period_amount(db: Session, client_id: int, product: models.Product, period: str) -> tuple[int, bool] | None:
    """A period's write-down and whether it is posted; None when the period writes nothing down."""
    start = _start_date(product)
    if (product.depreciation_method or "none") == "none" or start is None:
        return None
    elapsed = _months_elapsed(start, period)
    life = int(product.lifespan_months or 0)
    if elapsed < 0 or (life and elapsed >= life) or elapsed % _months_in(product.depreciation_interval or "monthly"):
        return None
    posted = db.query(models.ProductDepreciation.amount_minor).filter(
        models.ProductDepreciation.client_id == client_id,
        models.ProductDepreciation.product_id == product.id,
        models.ProductDepreciation.period == period,
    ).scalar()
    if posted is not None:
        return int(posted), True
    try:
        due = due_minor(db, client_id, product, period)
    except Invalid:
        return None
    return (due, False) if due > 0 else None


def schedule(db: Session, client_id: int, product_id: int) -> dict:
    product = _get_product(db, client_id, product_id)
    currency = get_client_currency(db, client_id)
    price = int(product.purchase_price_minor or 0)
    posted = posted_minor(db, client_id, product.id)
    period = _next_period(db, client_id, product)
    due = 0
    reason = None
    if (product.depreciation_method or "none") == "none":
        reason = "No depreciation method is set"
    elif period is None:
        reason = "No purchase date or start date is set"
    elif price <= 0:
        reason = "No purchase price is recorded"
    else:
        try:
            due = due_minor(db, client_id, product, period)
        except Invalid as error:
            reason = str(error)
    return {
        "product_id": product.id,
        "currency": currency,
        "method": product.depreciation_method or "none",
        "interval": product.depreciation_interval or "monthly",
        "purchase_price_minor": price,
        "posted_minor": posted,
        "book_value_minor": max(0, price - posted),
        "next_period": period,
        "due_minor": due,
        "blocked_reason": reason,
    }


def validate_automatic(db: Session, client_id: int, product: models.Product) -> None:
    if not product.auto_depreciation:
        return
    if not product.is_asset or product.depreciation_method == "none":
        raise Invalid("Automatic depreciation needs a fixed asset and a depreciation method")
    if not product.depreciation_interval or _start_date(product) is None:
        raise Invalid("Set a depreciation interval and a purchase date or start date first")
    if not product.purchase_price_minor or product.purchase_price_minor <= 0 or not product.lifespan_months or product.lifespan_months <= 0:
        raise Invalid("Depreciation needs a purchase price and a lifespan in months")
    if product.depreciation_method == "declining_balance" and not (product.depreciation_annual_rate or 0) > 0:
        raise Invalid("Declining-balance depreciation needs an annual rate above zero")
    if not product.depreciation_expense_account_id or not product.depreciation_asset_account_id:
        raise Invalid("Set both the depreciation expense account and the asset account first")
    for account_id in (product.depreciation_expense_account_id, product.depreciation_asset_account_id):
        if ledger_service.get_account(db, client_id, account_id) is None:
            raise Invalid(f"Account {account_id} not found for this client")


def _post(
    db: Session, client_id: int, product_id: int, *, period: str,
) -> tuple[models.Transaction, models.ProductDepreciation]:
    start = _validate_period(period)
    product = _get_product(db, client_id, product_id)

    if (product.depreciation_method or "none") == "none":
        raise Invalid("This product has no depreciation method")
    if not product.depreciation_expense_account_id or not product.depreciation_asset_account_id:
        raise Invalid("Set both the depreciation expense account and the asset account first")
    for account_id in (product.depreciation_expense_account_id, product.depreciation_asset_account_id):
        if ledger_service.get_account(db, client_id, account_id) is None:
            raise Invalid(f"Account {account_id} not found for this client")

    begins = _start_date(product)
    if begins is None:
        raise Invalid("Set a purchase date or a depreciation start date first")
    if start < begins.replace(day=1):
        raise Invalid(f"Depreciation starts in {_period_key(begins)}")

    already = db.query(models.ProductDepreciation).filter(
        models.ProductDepreciation.client_id == client_id,
        models.ProductDepreciation.product_id == product.id,
        models.ProductDepreciation.period == period,
    ).first()
    if already is not None:
        raise Invalid(f"{period} has already been posted for this product")

    amount = due_minor(db, client_id, product, period)
    if amount <= 0:
        raise Invalid("Nothing left to depreciate")

    currency = get_client_currency(db, client_id)
    posting_date = _posting_date(period)
    transaction = ledger_service.create_transaction(
        db,
        client_id=client_id,
        date=posting_date,
        description=f"減価償却：{product.name}（{period}）",
        amount_minor=amount,
        currency=currency,
        legs=[
            Leg(product.depreciation_expense_account_id, debit=amount),
            Leg(product.depreciation_asset_account_id, credit=amount),
        ],
    )
    row = models.ProductDepreciation(
        client_id=client_id, product_id=product.id, period=period,
        transaction_id=transaction.id, amount_minor=amount,
    )
    db.add(row)
    db.flush()
    return transaction, row


# How many periods one automatic run writes down per product. A schedule switched
# on long after the purchase catches up over several runs, as recurring does.
CATCH_UP_LIMIT = 24


def post_due(
    db: Session, client_id: int, product_id: int, *, today: Date, limit: int = CATCH_UP_LIMIT,
) -> list[models.ProductDepreciation]:
    """Write down every ended period in order, without committing.

    Stops at the first period that has not ended or once nothing is left, so a
    run never posts ahead of the calendar.
    """
    product = _get_product(db, client_id, product_id)
    rows: list[models.ProductDepreciation] = []
    while len(rows) < limit:
        period = _next_period(db, client_id, product)
        if period is None or _posting_date(period) > today:
            break
        if due_minor(db, client_id, product, period) <= 0:
            break
        _, row = _post(db, client_id, product.id, period=period)
        rows.append(row)
    return rows
