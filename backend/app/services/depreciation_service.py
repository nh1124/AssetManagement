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

from ..domain.messages import Message, message_of
from .. import models, schemas
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
        raise Invalid("Period must be YYYY-MM", ja="期間はYYYY-MMで指定してください。") from error
    return start


def _get_product(db: Session, client_id: int, product_id: int) -> models.Product:
    product = db.query(models.Product).filter(
        models.Product.id == product_id,
        models.Product.client_id == client_id,
    ).first()
    if product is None:
        raise Invalid("Product not found for this client", ja="物品が見つかりません。")
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
        raise Invalid("Depreciation needs a lifespan in months", ja="減価償却には耐用月数が必要です。")
    start = _start_date(product)
    if start is None:
        raise Invalid("Set a purchase date or a depreciation start date first", ja="先に購入日か償却の開始日を設定してください。")

    months = _months_in(product.depreciation_interval or "monthly")
    method = product.depreciation_method or "none"
    if method == "straight_line":
        amount = Money(price, currency).allocate([1] * life)[0].minor * months
    elif method == "declining_balance":
        rate = float(product.depreciation_annual_rate or 0.0)
        if rate <= 0:
            raise Invalid("Declining-balance depreciation needs an annual rate above zero", ja="定率法には0より大きい年償却率が必要です。")
        amount = int(remaining * rate / 100.0 / 12.0 * months)
    else:
        raise Invalid("This product has no depreciation method", ja="この物品には減価償却の方法が設定されていません。")

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
        reason = Message("No depreciation method is set", ja="減価償却の方法が設定されていません")
    elif period is None:
        reason = Message("No purchase date or start date is set", ja="購入日も償却の開始日も設定されていません")
    elif price <= 0:
        reason = Message("No purchase price is recorded", ja="購入価格が記録されていません")
    else:
        try:
            due = due_minor(db, client_id, product, period)
        except Invalid as error:
            reason = message_of(error)
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
        raise Invalid("Automatic depreciation needs a fixed asset and a depreciation method", ja="自動の減価償却には固定資産と償却の方法が必要です。")
    if not product.depreciation_interval or _start_date(product) is None:
        raise Invalid(
            "Set a depreciation interval and a purchase date or start date first",
            ja="先に償却の間隔と、購入日か償却の開始日を設定してください。",
        )
    if not product.purchase_price_minor or product.purchase_price_minor <= 0 or not product.lifespan_months or product.lifespan_months <= 0:
        raise Invalid("Depreciation needs a purchase price and a lifespan in months", ja="減価償却には購入価格と耐用月数が必要です。")
    if product.depreciation_method == "declining_balance" and not (product.depreciation_annual_rate or 0) > 0:
        raise Invalid("Declining-balance depreciation needs an annual rate above zero", ja="定率法には0より大きい年償却率が必要です。")
    if not product.depreciation_expense_account_id or not product.depreciation_asset_account_id:
        raise Invalid(
            "Set both the depreciation expense account and the asset account first",
            ja="先に減価償却費の科目と資産口座の両方を設定してください。",
        )
    for account_id in (product.depreciation_expense_account_id, product.depreciation_asset_account_id):
        if ledger_service.get_account(db, client_id, account_id) is None:
            raise Invalid(f"Account {account_id} not found for this client", ja=f"口座・科目が見つかりません（#{account_id}）。")


def _post(
    db: Session, client_id: int, product_id: int, *, period: str,
    amount_minor: int | None = None, posting_date: Date | None = None, expense_account_id: int | None = None,
) -> tuple[models.Transaction, models.ProductDepreciation]:
    """Write one period down. A hand-recorded write-down may name its own amount, date and expense."""
    start = _validate_period(period)
    product = _get_product(db, client_id, product_id)
    expense_account_id = expense_account_id or product.depreciation_expense_account_id

    if amount_minor is None and (product.depreciation_method or "none") == "none":
        raise Invalid("This product has no depreciation method", ja="この物品には減価償却の方法が設定されていません。")
    if not expense_account_id or not product.depreciation_asset_account_id:
        raise Invalid(
            "Set both the depreciation expense account and the asset account first",
            ja="先に減価償却費の科目と資産口座の両方を設定してください。",
        )
    for account_id in (expense_account_id, product.depreciation_asset_account_id):
        if ledger_service.get_account(db, client_id, account_id) is None:
            raise Invalid(f"Account {account_id} not found for this client", ja=f"口座・科目が見つかりません（#{account_id}）。")

    begins = _start_date(product)
    if begins is None:
        raise Invalid("Set a purchase date or a depreciation start date first", ja="先に購入日か償却の開始日を設定してください。")
    if start < begins.replace(day=1):
        raise Invalid(f"Depreciation starts in {_period_key(begins)}", ja=f"減価償却は{_period_key(begins)}から始まります。")

    already = db.query(models.ProductDepreciation).filter(
        models.ProductDepreciation.client_id == client_id,
        models.ProductDepreciation.product_id == product.id,
        models.ProductDepreciation.period == period,
    ).first()
    if already is not None:
        raise Invalid(f"{period} has already been posted for this product", ja=f"この物品の{period}の減価償却は記録済みです。")

    remaining = int(product.purchase_price_minor or 0) - posted_minor(db, client_id, product.id)
    if amount_minor is None:
        amount = due_minor(db, client_id, product, period)
    elif not 0 < amount_minor <= remaining:
        raise Invalid("金額は0より大きく、帳簿価額以下にしてください。", en="The amount must be above zero and no more than the book value.")
    else:
        amount = amount_minor
    if amount <= 0:
        raise Invalid("Nothing left to depreciate", ja="償却する残りはありません。")

    currency = get_client_currency(db, client_id)
    transaction = ledger_service.create_transaction(
        db,
        client_id=client_id,
        date=posting_date or _posting_date(period),
        description=f"減価償却：{product.name}（{period}）",
        amount_minor=amount,
        currency=currency,
        legs=[
            Leg(expense_account_id, debit=amount),
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


def _account_of_type(db: Session, client_id: int, account_id: int, account_type: str, label: str) -> int:
    account = ledger_service.get_account(db, client_id, account_id)
    if account is None or account.account_type != account_type:
        raise Invalid(f"同じクライアントの{label}を選んでください。", en=f"Choose an {account_type} account of this client.")
    return account.id


def record(
    db: Session, client_id: int, product_id: int, *, period: str, amount_minor: int | None = None,
    posting_date: Date | None = None, expense_account_id: int | None = None, asset_account_id: int | None = None,
) -> tuple[models.Transaction, models.ProductDepreciation]:
    """A write-down recorded by hand from the ledger, linked exactly like an automatic one.

    The product keeps the accounts it was missing, so the next write-down, by hand
    or automatic, needs no second choice.
    """
    product = _get_product(db, client_id, product_id)
    if not product.is_asset:
        raise Invalid("固定資産を選んでください。", en="Choose a fixed asset.")
    if expense_account_id is not None:
        expense_account_id = _account_of_type(db, client_id, expense_account_id, "expense", "費用科目")
        product.depreciation_expense_account_id = product.depreciation_expense_account_id or expense_account_id
    if asset_account_id is not None:
        asset_account_id = _account_of_type(db, client_id, asset_account_id, "asset", "資産口座")
        product.depreciation_asset_account_id = product.depreciation_asset_account_id or asset_account_id
    return _post(db, client_id, product.id, period=period, amount_minor=amount_minor,
                 posting_date=posting_date, expense_account_id=expense_account_id)


def _record_of(db: Session, client_id: int, depreciation_id: int) -> models.ProductDepreciation:
    row = db.query(models.ProductDepreciation).filter_by(client_id=client_id, id=depreciation_id).first()
    if row is None:
        raise Invalid("減価償却の記録が見つかりません。", en="Depreciation record not found.")
    return row


def amend(
    db: Session, client_id: int, depreciation_id: int, *, amount_minor: int,
    posting_date: Date | None = None, expense_account_id: int | None = None,
) -> tuple[models.Transaction, models.ProductDepreciation]:
    """Change a posted write-down's amount, date or expense; the entry and the record move together."""
    row = _record_of(db, client_id, depreciation_id)
    product = _get_product(db, client_id, row.product_id)
    room = int(product.purchase_price_minor or 0) - posted_minor(db, client_id, product.id) + int(row.amount_minor)
    if not 0 < amount_minor <= room:
        raise Invalid("金額は0より大きく、帳簿価額以下にしてください。", en="The amount must be above zero and no more than the book value.")
    transaction = db.query(models.Transaction).filter_by(client_id=client_id, id=row.transaction_id).first()
    # Read the legs as values: the rebuild below replaces the leg rows themselves.
    legs = db.query(models.JournalEntry.account_id, models.JournalEntry.debit_minor).filter_by(transaction_id=transaction.id).all()
    expense = next((account for account, debit in legs if (debit or 0) > 0), None)
    if expense_account_id is not None:
        expense = _account_of_type(db, client_id, expense_account_id, "expense", "費用科目")
    credit = next((account for account, debit in legs if not debit), product.depreciation_asset_account_id)
    amount = Money(amount_minor, transaction.currency).to_float()
    ledger_service.update_transaction(db, transaction.id, schemas.TransactionUpdate(
        date=posting_date or transaction.date, amount=amount,
        legs=[schemas.TransactionLeg(account_id=expense, debit=amount), schemas.TransactionLeg(account_id=credit, credit=amount)],
    ), client_id, commit=False)
    row.amount_minor = amount_minor
    db.flush()
    return transaction, row


def follow_transaction(db: Session, client_id: int, transaction: models.Transaction) -> None:
    """After a generic edit of a write-down's entry, the record keeps the entry's amount."""
    row = db.query(models.ProductDepreciation).filter_by(client_id=client_id, transaction_id=transaction.id).first()
    if row is not None:
        row.amount_minor = transaction.amount_minor


def forget_transaction(db: Session, client_id: int, transaction_id: int) -> None:
    """Deleting a write-down's entry takes its record with it, so the book value comes back."""
    db.query(models.ProductDepreciation).filter_by(client_id=client_id, transaction_id=transaction_id).delete(synchronize_session="fetch")


def preview(db: Session, client_id: int, product_id: int) -> dict:
    """What recording the next write-down by hand would propose."""
    product = _get_product(db, client_id, product_id)
    plan = schedule(db, client_id, product_id)
    currency = plan["currency"]
    return {
        "product_id": product.id, "product_name": product.name, "currency": currency,
        "next_period": plan["next_period"],
        "due": Money(plan["due_minor"], currency).to_float(),
        "book_value": Money(plan["book_value_minor"], currency).to_float(),
        "expense_account_id": product.depreciation_expense_account_id,
        "asset_account_id": product.depreciation_asset_account_id,
        "blocked_reason": plan["blocked_reason"],
    }
