"""Accounting Service - Double-entry bookkeeping engine."""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Optional
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


def ensure_default_accounts(db: Session):
    """Create default accounts if they don't exist."""
    for acc in DEFAULT_ACCOUNTS:
        existing = db.query(models.Account).filter(models.Account.name == acc["name"]).first()
        if not existing:
            db.add(models.Account(**acc))
    db.commit()


def get_or_create_account(db: Session, name: str, account_type: str = "expense") -> models.Account:
    """Get account by name or create it."""
    account = db.query(models.Account).filter(models.Account.name == name.lower()).first()
    if not account:
        account = models.Account(name=name.lower(), account_type=account_type)
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


def process_transaction(db: Session, transaction: models.Transaction):
    """
    Process a transaction with double-entry bookkeeping.
    
    Rules:
    - Income: Debit Asset (from_account), Credit Income (category)
    - Expense: Debit Expense (category), Credit Asset (from_account)
    - Transfer: Debit to_account, Credit from_account
    """
    from_acc_name = transaction.from_account or "cash"
    to_acc_name = transaction.to_account or "expense"
    category = transaction.category or "expense"
    
    # Determine account types and get/create accounts
    if transaction.type == "Income":
        # Money comes IN: Debit Asset, Credit Income
        from_account = get_or_create_account(db, from_acc_name, "asset")
        to_account = get_or_create_account(db, category, "income")
        
        # Debit the asset (increase asset)
        debit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=from_account.id,
            debit=transaction.amount,
            credit=0
        )
        # Credit the income (increase income)
        credit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=to_account.id,
            debit=0,
            credit=transaction.amount
        )
        
        # Update balances
        from_account.balance += transaction.amount  # Asset increases
        
    elif transaction.type == "Expense":
        # Money goes OUT: Debit Expense, Credit Asset
        from_account = get_or_create_account(db, from_acc_name, "asset")
        to_account = get_or_create_account(db, category, "expense")
        
        # Debit the expense (increase expense)
        debit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=to_account.id,
            debit=transaction.amount,
            credit=0
        )
        # Credit the asset (decrease asset)
        credit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=from_account.id,
            debit=0,
            credit=transaction.amount
        )
        
        # Update balances
        from_account.balance -= transaction.amount  # Asset decreases
        
    else:  # Transfer
        from_account = get_or_create_account(db, from_acc_name, "asset")
        to_account = get_or_create_account(db, to_acc_name, "asset")
        
        # Debit to_account (increase), Credit from_account (decrease)
        debit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=to_account.id,
            debit=transaction.amount,
            credit=0
        )
        credit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=from_account.id,
            debit=0,
            credit=transaction.amount
        )
        
        # Update balances
        from_account.balance -= transaction.amount
        to_account.balance += transaction.amount
    
    db.add(debit_entry)
    db.add(credit_entry)
    db.commit()


def get_balance_sheet(db: Session, as_of_date: Optional[date] = None) -> dict:
    """
    Generate Balance Sheet snapshot.
    B/S = Assets - Liabilities = Equity
    """
    if as_of_date is None:
        as_of_date = date.today()
    
    # Get all accounts
    accounts = db.query(models.Account).all()
    
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
        "net_worth": net_worth
    }


def get_profit_loss(db: Session, year: int, month: int) -> dict:
    """
    Generate Profit & Loss statement for a specific month.
    P/L = Income - Expenses
    """
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    # Get transactions for the period
    transactions = db.query(models.Transaction).filter(
        and_(
            models.Transaction.date >= start_date,
            models.Transaction.date < end_date
        )
    ).all()
    
    income_by_category = {}
    expense_by_category = {}
    
    for tx in transactions:
        cat = tx.category or "Other"
        if tx.type == "Income":
            income_by_category[cat] = income_by_category.get(cat, 0) + tx.amount
        elif tx.type == "Expense":
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
        "net_profit_loss": net_pl
    }


def get_variance_analysis(db: Session, year: int, month: int) -> dict:
    """
    Compare actual spending vs budget for a specific month.
    """
    month_str = f"{year}-{month:02d}"
    
    # Get budgets for the month
    budgets = db.query(models.Budget).filter(models.Budget.month == month_str).all()
    
    # Get actual spending for the month
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    transactions = db.query(models.Transaction).filter(
        and_(
            models.Transaction.date >= start_date,
            models.Transaction.date < end_date,
            models.Transaction.type == "Expense"
        )
    ).all()
    
    actual_by_category = {}
    for tx in transactions:
        cat = tx.category or "Other"
        actual_by_category[cat] = actual_by_category.get(cat, 0) + tx.amount
    
    # Build variance report
    variance_items = []
    for budget in budgets:
        actual = actual_by_category.get(budget.category, 0)
        variance = budget.proposed_amount - actual
        variance_items.append({
            "category": budget.category,
            "budget": budget.proposed_amount,
            "actual": actual,
            "variance": variance,
            "percentage": (actual / budget.proposed_amount * 100) if budget.proposed_amount > 0 else 0
        })
    
    # Add categories with spending but no budget
    for cat, amount in actual_by_category.items():
        if not any(v["category"] == cat for v in variance_items):
            variance_items.append({
                "category": cat,
                "budget": 0,
                "actual": amount,
                "variance": -amount,
                "percentage": 100
            })
    
    total_budget = sum(v["budget"] for v in variance_items)
    total_actual = sum(v["actual"] for v in variance_items)
    
    return {
        "period": month_str,
        "items": variance_items,
        "total_budget": total_budget,
        "total_actual": total_actual,
        "total_variance": total_budget - total_actual
    }
