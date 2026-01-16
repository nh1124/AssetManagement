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


def ensure_default_accounts(db: Session, client_id: int):
    """Create default accounts for a client if they don't exist."""
    for acc in DEFAULT_ACCOUNTS:
        existing = db.query(models.Account).filter(
            models.Account.name == acc["name"],
            models.Account.client_id == client_id
        ).first()
        if not existing:
            db.add(models.Account(**acc, client_id=client_id))
    db.commit()


def get_or_create_account(db: Session, name: str, client_id: int, account_type: str = "expense") -> models.Account:
    """Get account by name or create it for a specific client."""
    account = db.query(models.Account).filter(
        models.Account.name == name.lower(),
        models.Account.client_id == client_id
    ).first()
    if not account:
        account = models.Account(name=name.lower(), account_type=account_type, client_id=client_id)
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


def process_transaction(db: Session, transaction: models.Transaction):
    """
    Process a transaction with double-entry bookkeeping.
    """
    client_id = transaction.client_id
    from_acc_name = transaction.from_account or "cash"
    to_acc_name = transaction.to_account or "expense"
    category = transaction.category or "expense"
    
    # Determine account types and get/create accounts
    if transaction.type == "Income":
        # Money comes IN: Debit Asset, Credit Income
        from_account = get_or_create_account(db, from_acc_name, client_id, "asset")
        to_account = get_or_create_account(db, category, client_id, "income")
        
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
        from_account.balance += transaction.amount
        
    elif transaction.type == "Expense":
        # Money goes OUT: Debit Expense, Credit Asset
        from_account = get_or_create_account(db, from_acc_name, client_id, "asset")
        to_account = get_or_create_account(db, category, client_id, "expense")
        
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
        from_account.balance -= transaction.amount
        
    elif transaction.type == "Debt":
        # Debt Repayment: Debit Liability, Credit Asset
        from_account = get_or_create_account(db, from_acc_name, client_id, "asset")
        to_account = get_or_create_account(db, to_acc_name, client_id, "liability")
        
        # Debit the liability (decrease debt)
        debit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=to_account.id,
            debit=transaction.amount,
            credit=0
        )
        # Credit the asset (decrease money)
        credit_entry = models.JournalEntry(
            transaction_id=transaction.id,
            account_id=from_account.id,
            debit=0,
            credit=transaction.amount
        )
        from_account.balance -= transaction.amount
        to_account.balance += transaction.amount # Liability balance + means less debt in this model logic for simplicity or logic check
        
    else:  # Transfer
        from_account = get_or_create_account(db, from_acc_name, client_id, "asset")
        to_account = get_or_create_account(db, to_acc_name, client_id, "asset")
        
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
        from_account.balance -= transaction.amount
        to_account.balance += transaction.amount
    
    db.add(debit_entry)
    db.add(credit_entry)
    db.commit()


def get_balance_sheet(db: Session, as_of_date: Optional[date] = None, client_id: int = None) -> dict:
    """
    Generate Balance Sheet snapshot for current client.
    """
    if as_of_date is None:
        as_of_date = date.today()
    
    # Get all accounts for client
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
        "net_worth": net_worth
    }


def get_profit_loss(db: Session, year: int, month: int, client_id: int = None) -> dict:
    """
    Generate Profit & Loss statement for a specific month and client.
    """
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    # Get transactions for the period and client
    transactions = db.query(models.Transaction).filter(
        and_(
            models.Transaction.client_id == client_id,
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


def get_variance_analysis(db: Session, year: int, month: int, client_id: int = None) -> dict:
    """
    Compare actual spending vs monthly budgets for a specific month and client.
    Uses models.MonthlyBudget (per account) joined with actual transactions.
    """
    month_str = f"{year}-{month:02d}"
    
    # Get all expense accounts for this client
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "expense",
        models.Account.is_active == True
    ).all()
    
    # Get monthly budgets for this period
    monthly_budgets = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.client_id == client_id,
        models.MonthlyBudget.target_period == month_str
    ).all()
    budget_map = {mb.account_id: mb.amount for mb in monthly_budgets}
    
    # Get actual spending for the month
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
        
    # We sum transactions by category, but wait, if we are doing account-based budgets,
    # we should probably look at transactions targeting those accounts.
    # In this system, 'category' in Transaction often matches account name.
    
    transactions = db.query(models.Transaction).filter(
        and_(
            models.Transaction.client_id == client_id,
            models.Transaction.date >= start_date,
            models.Transaction.date < end_date,
            models.Transaction.type == "Expense"
        )
    ).all()
    
    actual_by_category = {}
    for tx in transactions:
        cat = tx.category or "Other"
        actual_by_category[cat] = actual_by_category.get(cat, 0) + tx.amount
        
    variance_items = []
    
    for acc in accounts:
        actual = actual_by_category.get(acc.name, 0)
        # Fallback logic for budget: MonthlyBudget -> Account.budget_limit -> 0
        budget = budget_map.get(acc.id)
        if budget is None:
            budget = acc.budget_limit or 0.0
            
        variance = budget - actual
        variance_items.append({
            "category": acc.name,
            "budget": budget,
            "actual": actual,
            "variance": variance,
            "percentage": (actual / budget * 100) if budget > 0 else 0
        })
        
    # Add any categories that have spending but no corresponding expense account (rare in this model but safe)
    existing_cats = {acc.name for acc in accounts}
    for cat, amount in actual_by_category.items():
        if cat not in existing_cats:
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
