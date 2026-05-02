"""Analysis service - CFO logic and financial calculations."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, extract, func
from sqlalchemy.orm import Session

from .. import models


LIQUID_ACCOUNT_NAMES = {"cash", "bank", "savings"}
UPCOMING_OUTFLOW_TYPES = {"Expense", "LiabilityPayment", "CreditExpense"}
ACCOUNT_ROLES = ("defense", "growth", "earmarked", "operating", "unassigned")


def _cash_accounts(db: Session, client_id: int) -> list[models.Account]:
    return db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.name.in_(LIQUID_ACCOUNT_NAMES),
    ).all()


def _sum_liquid_assets(db: Session, client_id: int) -> float:
    return sum((account.balance or 0.0) for account in _cash_accounts(db, client_id))


def _sum_unpaid_liabilities(db: Session, client_id: int) -> float:
    liabilities = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "liability",
    ).all()
    return sum(abs(account.balance or 0.0) for account in liabilities)


def _sum_capsule_balance(db: Session, client_id: int) -> float:
    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id
    ).all()
    return sum(
        ((capsule.account.balance if capsule.account else capsule.current_balance) or 0.0)
        for capsule in capsules
    )


def _asset_accounts(db: Session, client_id: int) -> list[models.Account]:
    return db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "asset",
        models.Account.is_active.is_(True),
    ).all()


def calculate_idle_money(db: Session, client_id: int) -> dict:
    accounts = _asset_accounts(db, client_id)
    by_role = defaultdict(float)
    targets_by_role = defaultdict(float)

    for account in accounts:
        role = account.role or "unassigned"
        if role not in ACCOUNT_ROLES:
            role = "unassigned"
        by_role[role] += account.balance or 0.0
        if account.role_target_amount:
            targets_by_role[role] += account.role_target_amount

    total_liquid = sum(by_role.values())
    defense_target = targets_by_role["defense"]
    defense_excess = max(0.0, by_role["defense"] - defense_target) if defense_target > 0 else 0.0
    idle_money = by_role["unassigned"] + defense_excess
    role_rows = []

    for role in ACCOUNT_ROLES:
        balance = by_role[role]
        target = targets_by_role[role] or None
        idle_component = 0.0
        if role == "unassigned":
            status = "Idle" if balance > 0 else "OK"
            idle_component = balance
        elif role == "defense" and target:
            excess = balance - target
            if excess > 0:
                status = "Over"
                idle_component = excess
            elif excess < 0:
                status = "Short"
            else:
                status = "OK"
        elif role == "earmarked":
            status = "Tied to goals"
        else:
            status = "OK"

        role_rows.append(
            {
                "role": role,
                "balance": round(balance, 0),
                "target": round(target, 0) if target is not None else None,
                "status": status,
                "idle_component": round(idle_component, 0),
            }
        )

    return {
        "by_role": {role: round(by_role[role], 0) for role in ACCOUNT_ROLES},
        "by_role_rows": role_rows,
        "idle_money": round(idle_money, 0),
        "idle_money_rate": round((idle_money / total_liquid * 100) if total_liquid > 0 else 0.0, 1),
        "total_liquid": round(total_liquid, 0),
    }


def _upcoming_recurring_total(db: Session, client_id: int, days: int = 30) -> float:
    today = date.today()
    horizon = today + timedelta(days=days)
    rows = db.query(models.RecurringTransaction).filter(
        and_(
            models.RecurringTransaction.client_id == client_id,
            models.RecurringTransaction.is_active.is_(True),
            models.RecurringTransaction.next_due_date.isnot(None),
            models.RecurringTransaction.next_due_date >= today,
            models.RecurringTransaction.next_due_date <= horizon,
            models.RecurringTransaction.type.in_(UPCOMING_OUTFLOW_TYPES),
        )
    ).all()
    return sum((row.amount or 0.0) for row in rows)


def calculate_logical_balance(db: Session, client_id: int) -> float:
    return (
        _sum_liquid_assets(db, client_id)
        - _sum_unpaid_liabilities(db, client_id)
        - _upcoming_recurring_total(db, client_id, days=30)
        - _sum_capsule_balance(db, client_id)
    )


def _roadmap_progression_status(goal_data: dict) -> str:
    goals = goal_data.get("goals") or []
    total_target = goal_data.get("total_target") or 0.0
    if not goals or total_target <= 0:
        return "On Track"

    weighted_progress = sum(
        (goal.get("progress_percentage") or 0.0)
        * ((goal.get("target_amount") or 0.0) / total_target)
        for goal in goals
    )
    if weighted_progress >= 95:
        return "On Track"
    if weighted_progress >= 80:
        return "At Risk"
    return "Off Track"


def get_summary(db: Session, client_id: int) -> dict:
    """Calculate financial summary for a specific client."""
    from .accounting_service import (
        get_balance_sheet,
        get_profit_loss,
        get_variance_analysis,
    )
    from .goal_service import calculate_overall_goal_probability

    bs = get_balance_sheet(db, client_id=client_id)
    today = date.today()
    pl = get_profit_loss(db, today.year, today.month, client_id=client_id)
    goal_data = calculate_overall_goal_probability(db, client_id=client_id)

    cash_accounts = _cash_accounts(db, client_id)
    total_cash = sum(a.balance for a in cash_accounts) if cash_accounts else 0.0
    liquid_assets = total_cash

    cc_unpaid = _sum_unpaid_liabilities(db, client_id)

    month_str = f"{today.year}-{today.month:02d}"
    monthly_budgets = db.query(models.MonthlyBudget).filter(
        models.MonthlyBudget.client_id == client_id,
        models.MonthlyBudget.target_period == month_str,
    ).all()

    next_month_budget = sum(mb.amount for mb in monthly_budgets)

    total_capsule_balance = _sum_capsule_balance(db, client_id)

    effective_cash = total_cash - cc_unpaid - next_month_budget - total_capsule_balance
    logical_balance = calculate_logical_balance(db, client_id)

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
    runway_months = (
        (logical_balance / avg_monthly_expense)
        if avg_monthly_expense > 0
        else None
    )

    forecast_3m = avg_monthly_expense * 3
    liquidity_coverage_ratio = (liquid_assets / forecast_3m * 100) if forecast_3m > 0 else 100.0

    idle_money = calculate_idle_money(db, client_id)
    roadmap_progression = _roadmap_progression_status(goal_data)

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

    runway_text = (
        f"runway {runway_months:.1f} months"
        if runway_months is not None
        else "runway unavailable"
    )
    cfo_briefing = (
        f"Net worth ¥{bs['net_worth']:,.0f}, monthly P/L ¥{pl['net_profit_loss']:,.0f}, "
        f"savings rate {savings_rate:.1f}%, {runway_text}."
    )

    return {
        "net_worth": bs["net_worth"],
        "monthly_pl": pl["net_profit_loss"],
        "liability_total": bs["total_liabilities"],
        "effective_cash": round(effective_cash, 0),
        "logical_balance": round(logical_balance, 0),
        "goal_probability": goal_data["overall_probability"],
        "total_goal_amount": goal_data["total_target"],
        "total_funded": goal_data["total_projected"],
        "cfo_briefing": cfo_briefing,
        "savings_rate": round(savings_rate, 1),
        "idle_money_rate": idle_money["idle_money_rate"],
        "idle_money": idle_money["idle_money"],
        "idle_money_by_role": idle_money["by_role_rows"],
        "liquidity_coverage_ratio": round(liquidity_coverage_ratio, 1),
        "runway_months": round(runway_months, 1) if runway_months is not None else None,
        "roadmap_progression": roadmap_progression,
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
    from .goal_service import calculate_overall_goal_probability

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


def _calc_net_worth_at(db: Session, client_id: int, as_of: date) -> dict:
    rows = db.query(
        models.Account.account_type,
        func.sum(models.JournalEntry.debit).label("debit"),
        func.sum(models.JournalEntry.credit).label("credit"),
    ).join(
        models.JournalEntry,
        models.JournalEntry.account_id == models.Account.id,
    ).join(
        models.Transaction,
        models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(
        models.Transaction.client_id == client_id,
        models.Transaction.date <= as_of,
    ).group_by(models.Account.account_type).all()

    assets = 0.0
    liabilities = 0.0
    for account_type, debit, credit in rows:
        debit = debit or 0.0
        credit = credit or 0.0
        if account_type in ("asset", "item"):
            assets += debit - credit
        elif account_type == "liability":
            liabilities += credit - debit

    return {
        "assets": assets,
        "liabilities": liabilities,
        "net_worth": assets - liabilities,
    }


def get_net_worth_history(db: Session, client_id: int, months: int = 36) -> list[dict]:
    months = max(1, min(months, 240))
    today = date.today()
    history = []

    for i in range(months - 1, -1, -1):
        target = today.replace(day=1) - relativedelta(months=i)
        eom = target + relativedelta(months=1, days=-1)
        values = _calc_net_worth_at(db, client_id, eom)
        history.append(
            {
                "period": eom.strftime("%Y-%m"),
                "net_worth": round(values["net_worth"], 2),
                "assets": round(values["assets"], 2),
                "liabilities": round(values["liabilities"], 2),
            }
        )

    return history
