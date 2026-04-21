"""Accounting Service - Double-entry bookkeeping engine."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from .. import models

# Default accounts to create on startup
DEFAULT_ACCOUNTS = [
    # Asset accounts
    {"name": "cash", "account_type": "asset"},
    {"name": "bank", "account_type": "asset"},
    {"name": "investment", "account_type": "asset"},
    {"name": "savings", "account_type": "asset"},
    # Liability accounts
    {"name": "credit", "account_type": "liability"},
    {"name": "loan", "account_type": "liability"},
    # Income accounts
    {"name": "salary", "account_type": "income"},
    {"name": "bonus", "account_type": "income"},
    {"name": "investment_income", "account_type": "income"},
    # Expense accounts
    {"name": "food", "account_type": "expense"},
    {"name": "transport", "account_type": "expense"},
    {"name": "entertainment", "account_type": "expense"},
    {"name": "utilities", "account_type": "expense"},
    {"name": "shopping", "account_type": "expense"},
    {"name": "expense", "account_type": "expense"},  # Generic expense
]


def ensure_default_accounts(db: Session, client_id: int) -> None:
    """Create default accounts for a client if they don't exist."""
    for acc in DEFAULT_ACCOUNTS:
        existing = db.query(models.Account).filter(
            models.Account.name == acc["name"],
            models.Account.client_id == client_id,
        ).first()
        if not existing:
            db.add(models.Account(**acc, client_id=client_id))
    db.commit()


def get_or_create_account(
    db: Session,
    name: str,
    client_id: int,
    account_type: str = "expense",
) -> models.Account:
    """Get account by name or create it for a specific client."""
    normalized = (name or "").strip().lower()
    if not normalized:
        normalized = "expense"

    account = db.query(models.Account).filter(
        models.Account.name == normalized,
        models.Account.client_id == client_id,
    ).first()
    if not account:
        account = models.Account(
            name=normalized,
            account_type=account_type,
            client_id=client_id,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


def _get_account_by_id(
    db: Session,
    account_id: Optional[int],
    client_id: int,
) -> Optional[models.Account]:
    if not account_id:
        return None
    return db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
    ).first()


def _resolve_account(
    db: Session,
    client_id: int,
    account_id: Optional[int],
    account_name: Optional[str],
    fallback_name: str,
    fallback_type: str,
) -> models.Account:
    by_id = _get_account_by_id(db, account_id, client_id)
    if by_id:
        return by_id

    if account_name:
        return get_or_create_account(db, account_name, client_id, fallback_type)

    return get_or_create_account(db, fallback_name, client_id, fallback_type)


def process_transaction(db: Session, transaction: models.Transaction) -> None:
    """
    Process a transaction with double-entry bookkeeping.
    """
    client_id = transaction.client_id
    if client_id is None:
        raise ValueError("transaction.client_id is required")

    category = transaction.category or "expense"

    if transaction.type == "Income":
        from_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.from_account_id,
            account_name=transaction.from_account,
            fallback_name="cash",
            fallback_type="asset",
        )
        to_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.to_account_id,
            account_name=transaction.to_account or category,
            fallback_name=category,
            fallback_type="income",
        )
        from_account.balance += transaction.amount

    elif transaction.type == "Expense":
        from_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.from_account_id,
            account_name=transaction.from_account,
            fallback_name="cash",
            fallback_type="asset",
        )
        to_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.to_account_id,
            account_name=transaction.to_account or category,
            fallback_name=category,
            fallback_type="expense",
        )
        from_account.balance -= transaction.amount

    elif transaction.type == "LiabilityPayment":
        from_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.from_account_id,
            account_name=transaction.from_account,
            fallback_name="cash",
            fallback_type="asset",
        )
        to_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.to_account_id,
            account_name=transaction.to_account,
            fallback_name="loan",
            fallback_type="liability",
        )
        from_account.balance -= transaction.amount
        # In this app model, liability account balance increases on repayment.
        to_account.balance += transaction.amount

    else:  # Transfer
        from_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.from_account_id,
            account_name=transaction.from_account,
            fallback_name="cash",
            fallback_type="asset",
        )
        to_account = _resolve_account(
            db=db,
            client_id=client_id,
            account_id=transaction.to_account_id,
            account_name=transaction.to_account,
            fallback_name="savings",
            fallback_type="asset",
        )
        from_account.balance -= transaction.amount
        to_account.balance += transaction.amount

    # Persist resolved account linkage for read APIs.
    transaction.from_account_id = from_account.id
    transaction.to_account_id = to_account.id
    transaction.from_account = from_account.name
    transaction.to_account = to_account.name

    debit_entry = models.JournalEntry(
        transaction_id=transaction.id,
        account_id=to_account.id if transaction.type == "Expense" else from_account.id,
        debit=transaction.amount,
        credit=0,
    )
    credit_entry = models.JournalEntry(
        transaction_id=transaction.id,
        account_id=from_account.id if transaction.type == "Expense" else to_account.id,
        debit=0,
        credit=transaction.amount,
    )

    if transaction.type == "Transfer":
        debit_entry.account_id = to_account.id
        credit_entry.account_id = from_account.id
    elif transaction.type == "LiabilityPayment":
        debit_entry.account_id = to_account.id
        credit_entry.account_id = from_account.id
    elif transaction.type == "Income":
        debit_entry.account_id = from_account.id
        credit_entry.account_id = to_account.id

    db.add(debit_entry)
    db.add(credit_entry)
    db.commit()


def revert_transaction(db: Session, transaction: models.Transaction) -> None:
    """
    Revert the impact of a transaction on account balances before deletion.
    """
    client_id = transaction.client_id
    if client_id is None:
        return

    from_account = _get_account_by_id(db, transaction.from_account_id, client_id)
    to_account = _get_account_by_id(db, transaction.to_account_id, client_id)

    if not from_account and transaction.from_account:
        from_account = db.query(models.Account).filter(
            models.Account.client_id == client_id,
            models.Account.name == transaction.from_account,
        ).first()
    if not to_account and transaction.to_account:
        to_account = db.query(models.Account).filter(
            models.Account.client_id == client_id,
            models.Account.name == transaction.to_account,
        ).first()

    if transaction.type == "Income":
        if from_account:
            from_account.balance -= transaction.amount
    elif transaction.type == "Expense":
        if from_account:
            from_account.balance += transaction.amount
    elif transaction.type == "LiabilityPayment":
        if from_account:
            from_account.balance += transaction.amount
        if to_account:
            to_account.balance -= transaction.amount
    else:  # Transfer
        if from_account:
            from_account.balance += transaction.amount
        if to_account:
            to_account.balance -= transaction.amount

    db.commit()


def get_balance_sheet(
    db: Session,
    as_of_date: Optional[date] = None,
    client_id: int | None = None,
) -> dict:
    """
    Generate Balance Sheet snapshot for current client.
    """
    if as_of_date is None:
        as_of_date = date.today()

    accounts = db.query(models.Account).filter(models.Account.client_id == client_id).all()

    assets = []
    liabilities = []
    for acc in accounts:
        if acc.account_type == "asset":
            assets.append({"name": acc.name, "balance": acc.balance})
        elif acc.account_type == "liability":
            liabilities.append({"name": acc.name, "balance": abs(acc.balance)})

    total_assets = sum(a["balance"] for a in assets)
    total_liabilities = sum(l["balance"] for l in liabilities)
    net_worth = total_assets - total_liabilities

    return {
        "as_of_date": as_of_date.isoformat(),
        "assets": assets,
        "liabilities": liabilities,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
    }


def get_profit_loss(db: Session, year: int, month: int, client_id: int | None = None) -> dict:
    """
    Generate Profit & Loss statement for a specific month and client.
    """
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    transactions = db.query(models.Transaction).filter(
        and_(
            models.Transaction.client_id == client_id,
            models.Transaction.date >= start_date,
            models.Transaction.date < end_date,
        )
    ).all()

    income_by_category: dict[str, float] = {}
    expense_by_category: dict[str, float] = {}

    for tx in transactions:
        cat = tx.category or "Other"
        if tx.type == "Income":
            income_by_category[cat] = income_by_category.get(cat, 0) + tx.amount
        elif tx.type in ("Expense", "LiabilityPayment"):
            expense_by_category[cat] = expense_by_category.get(cat, 0) + tx.amount

    total_income = sum(income_by_category.values())
    total_expense = sum(expense_by_category.values())
    net_pl = total_income - total_expense

    return {
        "period": f"{year}-{month:02d}",
        "income": [{"category": k, "amount": v} for k, v in income_by_category.items()],
        "expenses": [{"category": k, "amount": v} for k, v in expense_by_category.items()],
        "total_income": total_income,
        "total_expenses": total_expense,
        "net_profit_loss": net_pl,
    }


def get_variance_analysis(
    db: Session,
    year: int,
    month: int,
    client_id: int | None = None,
) -> dict:
    """
    Compare actual spending vs monthly budgets for a specific month and client.
    Uses models.MonthlyBudget (per account) joined with actual transactions.
    """
    month_str = f"{year}-{month:02d}"

    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "expense",
        models.Account.is_active.is_(True),
    ).all()

    monthly_budgets = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.client_id == client_id,
        models.MonthlyBudget.target_period == month_str,
    ).all()
    budget_map = {mb.account_id: mb.amount for mb in monthly_budgets}
    account_name_to_id = {acc.name: acc.id for acc in accounts}

    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    transactions = db.query(models.Transaction).filter(
        and_(
            models.Transaction.client_id == client_id,
            models.Transaction.date >= start_date,
            models.Transaction.date < end_date,
            models.Transaction.type.in_(["Expense", "LiabilityPayment"]),
        )
    ).all()

    actual_by_account_id: dict[int, float] = {}
    orphan_actual_by_category: dict[str, float] = {}
    for tx in transactions:
        if tx.to_account_id and tx.to_account_id in account_name_to_id.values():
            actual_by_account_id[tx.to_account_id] = actual_by_account_id.get(tx.to_account_id, 0.0) + tx.amount
            continue

        if tx.category and tx.category in account_name_to_id:
            acc_id = account_name_to_id[tx.category]
            actual_by_account_id[acc_id] = actual_by_account_id.get(acc_id, 0.0) + tx.amount
        else:
            cat = tx.category or "Other"
            orphan_actual_by_category[cat] = orphan_actual_by_category.get(cat, 0.0) + tx.amount

    variance_items = []
    for acc in accounts:
        actual = actual_by_account_id.get(acc.id, 0.0)
        budget = budget_map.get(acc.id)
        if budget is None:
            budget = acc.budget_limit or 0.0

        variance = budget - actual
        variance_items.append(
            {
                "category": acc.name,
                "budget": budget,
                "actual": actual,
                "variance": variance,
                "percentage": (actual / budget * 100) if budget > 0 else 0,
            }
        )

    for cat, amount in orphan_actual_by_category.items():
        variance_items.append(
            {
                "category": cat,
                "budget": 0,
                "actual": amount,
                "variance": -amount,
                "percentage": 100,
            }
        )

    total_budget = sum(v["budget"] for v in variance_items)
    total_actual = sum(v["actual"] for v in variance_items)

    return {
        "period": month_str,
        "items": variance_items,
        "total_budget": total_budget,
        "total_actual": total_actual,
        "total_variance": total_budget - total_actual,
    }
