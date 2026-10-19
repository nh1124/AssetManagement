"""Analysis service - CFO logic and financial calculations."""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from .. import models
from .ledger_valuation import (
    calculate_account_valued_balance,
    calculate_account_valued_balances,
)
from .capsule_service import capsule_balance
from .budget_context import BudgetContext
from .budget_plan_store import find_budget_plan_id
from .budget_projection import planned_cash_outflow_remaining
from . import depreciation_service
from .fx_service import get_client_currency
from ..domain.money import Money
from .periods import current_period_key
from .journal_legs import legs_in_range
from .goal_service import goal_events_query
from .strategy_service import calculate_overall_goal_probability
from .reporting_service import (
    get_balance_sheet,
    get_profit_loss,
    get_variance_analysis,
)


def _cash_accounts(db: Session, client_id: int) -> list[models.Account]:
    return db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "asset",
        models.Account.is_active.is_(True),
    ).all()


def _sum_liquid_assets(db: Session, client_id: int) -> float:
    accounts = _cash_accounts(db, client_id)
    return sum(calculate_account_valued_balances(db, accounts).values())


def _sum_unpaid_liabilities(db: Session, client_id: int) -> float:
    liabilities = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "liability",
    ).all()
    balances = calculate_account_valued_balances(db, liabilities)
    return sum(abs(balance) for balance in balances.values())


def _sum_capsule_balance(db: Session, client_id: int) -> float:
    """Every capsule's attributed claim in the client's currency."""
    capsules = db.query(models.Capsule).filter(
        models.Capsule.client_id == client_id,
    ).all()
    return sum(capsule_balance(db, capsule) for capsule in capsules)


def calculate_logical_balance(
    db: Session,
    client_id: int,
    *,
    ctx: BudgetContext | None = None,
) -> float:
    if ctx is None:
        ctx = BudgetContext(db, client_id)
    return (
        _sum_liquid_assets(db, client_id)
        - _sum_unpaid_liabilities(db, client_id)
        # Expense and non_cash_budget reserve unposted spending; debt is already
        # covered by the whole outstanding liability balance above.
        - planned_cash_outflow_remaining(ctx, current_period_key())
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

    bs = get_balance_sheet(db, client_id=client_id)
    today = date.today()
    pl = get_profit_loss(db, today.year, today.month, client_id=client_id)
    goal_data = calculate_overall_goal_probability(db, client_id=client_id)

    cash_accounts = _cash_accounts(db, client_id)
    total_cash = sum(calculate_account_valued_balance(db, account) for account in cash_accounts) if cash_accounts else 0.0
    liquid_assets = total_cash

    cc_unpaid = _sum_unpaid_liabilities(db, client_id)

    month_str = f"{today.year}-{today.month:02d}"
    plan_id = find_budget_plan_id(db, client_id)
    monthly_plan_lines = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id == plan_id,
        models.MonthlyPlanLine.target_period == month_str,
        models.MonthlyPlanLine.line_type == "expense",
        models.MonthlyPlanLine.is_active.is_(True),
    ).all() if plan_id is not None else []

    next_month_budget = sum(line.amount for line in monthly_plan_lines)

    total_capsule_balance = _sum_capsule_balance(db, client_id)

    effective_cash = total_cash - cc_unpaid - next_month_budget - total_capsule_balance
    logical_balance = calculate_logical_balance(db, client_id)

    total_income = pl["total_income"]
    total_expense = pl["total_expenses"]
    fcf = total_income - total_expense
    savings_rate = (fcf / total_income * 100) if total_income > 0 else 0.0

    three_months_ago = today - relativedelta(months=3)
    recent_expenses = sum(
        leg.signed
        for leg in legs_in_range(db, client_id, three_months_ago, today, account_types={"expense"})
    )
    avg_monthly_expense = recent_expenses / 3 if recent_expenses > 0 else 1.0
    runway_months = (
        (logical_balance / avg_monthly_expense)
        if avg_monthly_expense > 0
        else None
    )

    forecast_3m = avg_monthly_expense * 3
    liquidity_coverage_ratio = (liquid_assets / forecast_3m * 100) if forecast_3m > 0 else 100.0

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

    goal_count = goal_events_query(db, client_id).filter(
        models.LifeEvent.direction == "expense",
    ).count()

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
        "liquidity_coverage_ratio": round(liquidity_coverage_ratio, 1),
        "runway_months": round(runway_months, 1) if runway_months is not None else None,
        "roadmap_progression": roadmap_progression,
        "monthly_transaction_count": tx_count,
        "total_goal_count": goal_count,
        "budget_usage_rate": round(budget_usage_rate, 1),
    }


def get_depreciation_summary(db: Session, client_id: int) -> dict:
    """What has actually been written down, read from the postings.

    This used to compute a straight line of its own, which was the only answer
    while nothing was posted. Now that depreciation is entered in the journal,
    a second calculation here would be a second answer to one question, and the
    two would part company the first time a posting was skipped or a method
    changed. The book value is the purchase price less what was posted, and the
    monthly figure is what the next posting is actually due to be.
    """
    products = db.query(models.Product).filter(
        models.Product.client_id == client_id,
        models.Product.is_asset.is_(True),
    ).order_by(models.Product.id).all()

    currency = get_client_currency(db, client_id)
    items = []
    total_book_value = 0.0
    total_depreciation = 0.0
    monthly_expense = 0.0

    for product in products:
        schedule = depreciation_service.schedule(db, client_id, product.id)
        price = Money(schedule["purchase_price_minor"], currency).to_float()
        posted = Money(schedule["posted_minor"], currency).to_float()
        book_value = Money(schedule["book_value_minor"], currency).to_float()
        due = Money(schedule["due_minor"], currency).to_float()
        if price <= 0 and posted <= 0:
            continue
        items.append({
            "product_id": product.id,
            "name": product.name,
            "purchase_price": price,
            "current_value": book_value,
            "total_depreciation": posted,
            "monthly_depreciation": due,
            "method": schedule["method"],
            "next_period": schedule["next_period"],
            "blocked_reason": schedule["blocked_reason"],
        })
        total_book_value += book_value
        total_depreciation += posted
        monthly_expense += due

    return {
        "items": items,
        "total_book_value": total_book_value,
        "total_depreciation": total_depreciation,
        "monthly_expense": monthly_expense,
    }


def get_net_position(db: Session, client_id: int) -> dict:
    """Calculate Net Position = Assets - Current Debt - Future Life Event Costs for current client."""

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
