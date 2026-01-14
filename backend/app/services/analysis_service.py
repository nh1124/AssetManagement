"""Analysis service - CFO logic and financial calculations."""
from sqlalchemy.orm import Session
from .. import models

def get_summary(db: Session) -> dict:
    """Calculate financial summary with CFO logic."""
    
    # Get total assets
    assets = db.query(models.Asset).all()
    total_assets = sum(a.value for a in assets) if assets else 4800000  # Mock default
    
    # Get total liabilities
    liabilities = db.query(models.Liability).all()
    total_liabilities = sum(l.balance for l in liabilities) if liabilities else 1245000  # Mock default
    
    # CFO Logic: Effective Cash Calculation
    # Effective Cash = Total Cash - CC Unpaid - Next Month's Essential Budget
    total_cash = 1500000  # TODO: Calculate from assets where category = 'Cash'
    cc_unpaid = 45000  # TODO: Get from liabilities where category = 'CreditCard'
    
    # Get next month's budget
    budgets = db.query(models.Budget).all()
    next_month_budget = sum(b.proposed_amount for b in budgets) if budgets else 137000
    
    effective_cash = total_cash - cc_unpaid - next_month_budget
    
    # Net Worth = Assets - Liabilities
    net_worth = total_assets - total_liabilities
    
    # Monthly P/L (simplified: sum of this month's income - expenses)
    # TODO: Calculate from actual transactions
    monthly_pl = 150000
    
    return {
        "net_worth": net_worth,
        "monthly_pl": monthly_pl,
        "liability_total": total_liabilities,
        "effective_cash": effective_cash,
        "cfo_briefing": f"Financial health stable. Net worth: ¥{net_worth:,.0f}. Effective cash reserves: ¥{effective_cash:,.0f}."
    }


def calculate_depreciation(product: models.Product) -> dict | None:
    """Calculate depreciation for assets > 30k JPY."""
    if not product.is_asset or not product.lifespan_months or product.last_price < 30000:
        return None
    
    from datetime import date
    
    daily_rate = product.last_price / (product.lifespan_months * 30)
    
    if product.last_purchase_date:
        days_since_purchase = (date.today() - product.last_purchase_date).days
        total_depreciation = daily_rate * days_since_purchase
        current_value = max(0, product.last_price - total_depreciation)
    else:
        current_value = product.last_price
        total_depreciation = 0
    
    return {
        "current_value": current_value,
        "total_depreciation": total_depreciation,
        "daily_rate": daily_rate
    }


def get_net_position(db: Session) -> dict:
    """Calculate Net Position = Assets - Current Debt - Future Life Event Costs."""
    assets = db.query(models.Asset).all()
    total_assets = sum(a.value for a in assets) if assets else 4800000
    
    liabilities = db.query(models.Liability).all()
    current_debt = sum(l.balance for l in liabilities) if liabilities else 1245000
    
    life_events = db.query(models.LifeEvent).all()
    future_costs = sum(
        max(0, e.target_amount - (e.funded_amount or 0)) 
        for e in life_events
    ) if life_events else 0
    
    net_position = total_assets - current_debt - future_costs
    
    return {
        "total_assets": total_assets,
        "current_debt": current_debt,
        "future_life_event_costs": future_costs,
        "net_position": net_position
    }
