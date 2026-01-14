"""Analysis service - CFO logic and financial calculations."""
from sqlalchemy.orm import Session
from datetime import date
from .. import models


def get_summary(db: Session, client_id: int) -> dict:
    """Calculate financial summary for a specific client."""
    from .accounting_service import get_balance_sheet, get_profit_loss
    from .strategy_service import calculate_overall_goal_probability
    
    # Get current B/S
    bs = get_balance_sheet(db, client_id=client_id)
    
    # Get current month P/L
    today = date.today()
    pl = get_profit_loss(db, today.year, today.month, client_id=client_id)
    
    # Get goal probability
    goal_data = calculate_overall_goal_probability(db, client_id=client_id)
    
    # CFO Effective Cash calculation
    cash_accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.name.in_(["cash", "bank", "savings"])
    ).all()
    total_cash = sum(a.balance for a in cash_accounts) if cash_accounts else 0
    
    # Get credit card balance (liability)
    cc_account = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.name == "credit"
    ).first()
    cc_unpaid = abs(cc_account.balance) if cc_account else 0
    
    # Get next month's essential budget
    month_str = f"{today.year}-{today.month:02d}"
    budgets = db.query(models.Budget).filter(
        models.Budget.client_id == client_id,
        models.Budget.month == month_str
    ).all()
    next_month_budget = sum(b.proposed_amount for b in budgets) if budgets else 0
    
    effective_cash = total_cash - cc_unpaid - next_month_budget
    
    return {
        "net_worth": bs["net_worth"],
        "monthly_pl": pl["net_profit_loss"],
        "liability_total": bs["total_liabilities"],
        "effective_cash": effective_cash,
        "goal_probability": goal_data["overall_probability"],
        "total_goal_amount": goal_data["total_target"],
        "total_funded": goal_data["total_projected"],
        "cfo_briefing": f"Net worth: ¥{bs['net_worth']:,.0f}. Monthly P/L: ¥{pl['net_profit_loss']:,.0f}. Goal probability: {goal_data['overall_probability']:.0f}%."
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
            "monthly_depreciation": purchase_price / product.lifespan_months
        }
    
    daily_rate = purchase_price / (product.lifespan_months * 30)
    days_since_purchase = (date.today() - purchase_date).days
    total_depreciation = daily_rate * days_since_purchase
    current_value = max(0, purchase_price - total_depreciation)
    
    return {
        "current_value": current_value,
        "total_depreciation": total_depreciation,
        "daily_rate": daily_rate,
        "monthly_depreciation": purchase_price / product.lifespan_months
    }


def get_depreciation_summary(db: Session, client_id: int) -> dict:
    """Get total depreciation for all asset products belonging to current client."""
    products = db.query(models.Product).filter(
        models.Product.client_id == client_id,
        models.Product.is_asset == True,
        models.Product.lifespan_months != None
    ).all()
    
    items = []
    total_book_value = 0
    total_depreciation = 0
    monthly_expense = 0
    
    for product in products:
        dep = calculate_depreciation(product)
        if dep:
            items.append({
                "name": product.name,
                "purchase_price": product.purchase_price or product.last_unit_price,
                "current_value": dep["current_value"],
                "total_depreciation": dep["total_depreciation"],
                "monthly_depreciation": dep["monthly_depreciation"]
            })
            total_book_value += dep["current_value"]
            total_depreciation += dep["total_depreciation"]
            monthly_expense += dep["monthly_depreciation"]
    
    return {
        "items": items,
        "total_book_value": total_book_value,
        "total_depreciation": total_depreciation,
        "monthly_expense": monthly_expense
    }


def get_net_position(db: Session, client_id: int) -> dict:
    """Calculate Net Position = Assets - Current Debt - Future Life Event Costs for current client."""
    from .accounting_service import get_balance_sheet
    from .strategy_service import calculate_overall_goal_probability
    
    bs = get_balance_sheet(db, client_id=client_id)
    goal_data = calculate_overall_goal_probability(db, client_id=client_id)
    
    # Future costs = target amounts - projected funded
    future_costs = max(0, goal_data["total_target"] - goal_data["total_projected"])
    
    net_position = bs["net_worth"] - future_costs
    
    return {
        "total_assets": bs["total_assets"],
        "current_debt": bs["total_liabilities"],
        "future_life_event_costs": future_costs,
        "net_position": net_position
    }
