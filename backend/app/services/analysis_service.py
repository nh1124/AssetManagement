"""Analysis service - CFO logic and financial calculations."""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from .. import models


def get_summary(db: Session, client_id: int) -> dict:
    """Calculate financial summary for a specific client."""
    from .accounting_service import (
        get_balance_sheet,
        get_profit_loss,
        get_variance_analysis,
    )
    from .strategy_service import calculate_overall_goal_probability

    bs = get_balance_sheet(db, client_id=client_id)
    today = date.today()
    pl = get_profit_loss(db, today.year, today.month, client_id=client_id)
    goal_data = calculate_overall_goal_probability(db, client_id=client_id)

    cash_accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.name.in_(["cash", "bank", "savings"]),
    ).all()
    total_cash = sum(a.balance for a in cash_accounts) if cash_accounts else 0.0
    liquid_assets = total_cash

    cc_account = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.name == "credit",
    ).first()
    cc_unpaid = abs(cc_account.balance) if cc_account else 0.0

    month_str = f"{today.year}-{today.month:02d}"
    monthly_budgets = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.client_id == client_id,
        models.MonthlyBudget.target_period == month_str,
    ).all()

    if monthly_budgets:
        next_month_budget = sum(mb.amount for mb in monthly_budgets)
    else:
        expense_accounts = db.query(models.Account).filter(
            models.Account.client_id == client_id,
            models.Account.account_type == "expense",
            models.Account.is_active.is_(True),
            models.Account.budget_limit.isnot(None),
        ).all()
        next_month_budget = sum(a.budget_limit or 0.0 for a in expense_accounts)

    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id
    ).all()
    total_capsule_balance = sum(
        (c.account.balance if c.account else c.current_balance) for c in capsules
    )

    effective_cash = total_cash - cc_unpaid - next_month_budget - total_capsule_balance

    total_income = pl["total_income"]
    total_expense = pl["total_expenses"]
    fcf = total_income - total_expense
    savings_rate = (fcf / total_income * 100) if total_income > 0 else 0.0

    three_months_ago = today - relativedelta(months=3)
    recent_expenses = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.client_id == client_id,
        models.Transaction.type.in_(["Expense", "CreditExpense"]),
        models.Transaction.date >= three_months_ago,
    ).scalar() or 0.0
    avg_monthly_expense = recent_expenses / 3 if recent_expenses > 0 else 1.0
    runway_months = (effective_cash / avg_monthly_expense) if avg_monthly_expense > 0 else 999.0

    forecast_3m = avg_monthly_expense * 3
    liquidity_coverage_ratio = (liquid_assets / forecast_3m * 100) if forecast_3m > 0 else 100.0

    allocated = 0.0
    for acc in cash_accounts:
        allocs = db.query(models.GoalAllocation).filter(
            models.GoalAllocation.account_id == acc.id
        ).all()
        used_pct = sum(a.allocation_percentage for a in allocs)
        allocated += acc.balance * min(used_pct / 100, 1.0)
    idle = max(0.0, total_cash - allocated - total_capsule_balance)
    idle_money_rate = (idle / total_cash * 100) if total_cash > 0 else 0.0

    variance = get_variance_analysis(db, today.year, today.month, client_id=client_id)
    total_budget = variance.get("total_budget", 0.0) or 0.0
    total_actual = variance.get("total_actual", 0.0) or 0.0
    budget_usage_rate = (total_actual / total_budget * 100) if total_budget > 0 else 0.0

    tx_count = db.query(func.count(models.Transaction.id)).filter(
        models.Transaction.client_id == client_id,
        extract("year", models.Transaction.date) == today.year,
        extract("month", models.Transaction.date) == today.month,
    ).scalar() or 0

    goal_count = db.query(func.count(models.LifeEvent.id)).filter(
        models.LifeEvent.client_id == client_id
    ).scalar() or 0

    cfo_briefing = (
        f"Net worth ¥{bs['net_worth']:,.0f}, monthly P/L ¥{pl['net_profit_loss']:,.0f}, "
        f"savings rate {savings_rate:.1f}%, runway {runway_months:.1f} months."
    )

    return {
        "net_worth": bs["net_worth"],
        "monthly_pl": pl["net_profit_loss"],
        "liability_total": bs["total_liabilities"],
        "effective_cash": round(effective_cash, 0),
        "goal_probability": goal_data["overall_probability"],
        "total_goal_amount": goal_data["total_target"],
        "total_funded": goal_data["total_projected"],
        "cfo_briefing": cfo_briefing,
        "savings_rate": round(savings_rate, 1),
        "idle_money_rate": round(idle_money_rate, 1),
        "liquidity_coverage_ratio": round(liquidity_coverage_ratio, 1),
        "runway_months": round(runway_months, 1),
        "monthly_transaction_count": tx_count,
        "total_goal_count": goal_count,
        "budget_usage_rate": round(budget_usage_rate, 1),
    }


def calculate_depreciation(product: models.Product) -> dict | None:
    """Calculate depreciation for assets > 30k JPY."""
    purchase_price = product.purchase_price or product.last_unit_price

    if not product.is_asset or not product.lifespan_months or purchase_price < 30000:
        return None

    purchase_date = product.purchase_date or product.last_purchase_date

    if not purchase_date:
        return {
            "current_value": purchase_price,
            "total_depreciation": 0,
            "daily_rate": purchase_price / (product.lifespan_months * 30),
            "monthly_depreciation": purchase_price / product.lifespan_months,
        }

    daily_rate = purchase_price / (product.lifespan_months * 30)
    days_since_purchase = (date.today() - purchase_date).days
    total_depreciation = daily_rate * days_since_purchase
    current_value = max(0, purchase_price - total_depreciation)

    return {
        "current_value": current_value,
        "total_depreciation": total_depreciation,
        "daily_rate": daily_rate,
        "monthly_depreciation": purchase_price / product.lifespan_months,
    }


def get_depreciation_summary(db: Session, client_id: int) -> dict:
    """Get total depreciation for all asset products belonging to current client."""
    products = db.query(models.Product).filter(
        models.Product.client_id == client_id,
        models.Product.is_asset.is_(True),
        models.Product.lifespan_months.isnot(None),
    ).all()

    items = []
    total_book_value = 0.0
    total_depreciation = 0.0
    monthly_expense = 0.0

    for product in products:
        dep = calculate_depreciation(product)
        if dep:
            items.append(
                {
                    "name": product.name,
                    "purchase_price": product.purchase_price or product.last_unit_price,
                    "current_value": dep["current_value"],
                    "total_depreciation": dep["total_depreciation"],
                    "monthly_depreciation": dep["monthly_depreciation"],
                }
            )
            total_book_value += dep["current_value"]
            total_depreciation += dep["total_depreciation"]
            monthly_expense += dep["monthly_depreciation"]

    return {
        "items": items,
        "total_book_value": total_book_value,
        "total_depreciation": total_depreciation,
        "monthly_expense": monthly_expense,
    }


def get_net_position(db: Session, client_id: int) -> dict:
    """Calculate Net Position = Assets - Current Debt - Future Life Event Costs for current client."""
    from .accounting_service import get_balance_sheet
    from .strategy_service import calculate_overall_goal_probability

    bs = get_balance_sheet(db, client_id=client_id)
    goal_data = calculate_overall_goal_probability(db, client_id=client_id)

    future_costs = max(0.0, goal_data["total_target"] - goal_data["total_projected"])
    net_position = bs["net_worth"] - future_costs

    return {
        "total_assets": bs["total_assets"],
        "current_debt": bs["total_liabilities"],
        "future_life_event_costs": future_costs,
        "net_position": net_position,
    }
