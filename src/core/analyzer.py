"""
Cash Flow Analyzer
Analyzes income, expenses, and calculates key financial metrics.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
import logging
from collections import defaultdict

from sqlalchemy import create_engine, func, and_, or_
from sqlalchemy.orm import Session

from models.schema import (
    Transaction,
    TransactionType,
    TransactionCategory,
    StandardCostParam,
    CostUnit,
)

logger = logging.getLogger(__name__)


@dataclass
class MonthlyFlow:
    """Cash flow for a single month"""
    year: int
    month: int
    income: Decimal = Decimal('0')
    essential_expenses: Decimal = Decimal('0')
    discretionary_expenses: Decimal = Decimal('0')
    total_expenses: Decimal = Decimal('0')
    net_flow: Decimal = Decimal('0')
    savings_rate: Decimal = Decimal('0')
    by_category: Dict[str, Decimal] = field(default_factory=dict)


@dataclass
class CashFlowSummary:
    """Summary of cash flow analysis"""
    analysis_period_start: date
    analysis_period_end: date
    total_income: Decimal
    total_expenses: Decimal
    total_essential: Decimal
    total_discretionary: Decimal
    average_monthly_income: Decimal
    average_monthly_expenses: Decimal
    average_savings_rate: Decimal
    free_cash_flow: Decimal
    monthly_flows: List[MonthlyFlow]
    expense_by_category: Dict[str, Decimal]
    income_by_category: Dict[str, Decimal]


@dataclass
class BurnRateAnalysis:
    """Burn rate and runway analysis"""
    monthly_burn_rate: Decimal
    liquid_assets: Decimal
    runway_months: int
    runway_date: date
    is_sustainable: bool  # runway > 6 months


@dataclass
class KPIDashboard:
    """Key Performance Indicators for dashboard"""
    # Net Worth
    net_worth_jpy: Decimal
    net_worth_change_mtd: Decimal
    net_worth_change_ytd: Decimal
    
    # Cash Flow
    savings_rate: Decimal
    free_cash_flow_monthly: Decimal
    
    # Runway
    runway_months: int
    
    # Goals
    goal_achievement_rate: Decimal
    idle_money_rate: Decimal
    
    # Health Indicators
    is_healthy: bool
    
    # Optional fields with defaults
    savings_rate_target: Decimal = Decimal('0.20')
    runway_target: int = 6


class CashFlowAnalyzer:
    """Analyzer for cash flow and financial KPIs"""
    
    def __init__(self, db_url: str = "sqlite:///data/assets.db"):
        self.engine = create_engine(db_url)
    
    def analyze_cash_flow(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        months: int = 12
    ) -> CashFlowSummary:
        """
        Analyze cash flow for a period.
        
        Args:
            start_date: Start of analysis period (default: months ago)
            end_date: End of analysis period (default: today)
            months: Number of months if start_date not specified
        
        Returns:
            CashFlowSummary with detailed analysis
        """
        end_date = end_date or date.today()
        if start_date is None:
            # Go back N months
            if end_date.month > months:
                start_date = date(end_date.year, end_date.month - months, 1)
            else:
                years_back = (months - end_date.month) // 12 + 1
                month_back = (end_date.month - months) % 12
                if month_back <= 0:
                    month_back += 12
                start_date = date(end_date.year - years_back, month_back, 1)
        
        monthly_flows = []
        expense_by_category: Dict[str, Decimal] = defaultdict(Decimal)
        income_by_category: Dict[str, Decimal] = defaultdict(Decimal)
        
        with Session(self.engine) as session:
            # Load category lookup
            categories = {cat.id: cat for cat in session.query(TransactionCategory).all()}
            
            # Get all transactions in period
            transactions = session.query(Transaction).filter(
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date,
                Transaction.type.in_([
                    TransactionType.INCOME.value,
                    TransactionType.EXPENSE.value,
                    TransactionType.DEPRECIATION.value,
                ])
            ).all()
            
            # Group by month
            by_month: Dict[Tuple[int, int], List[Transaction]] = defaultdict(list)
            for tx in transactions:
                key = (tx.transaction_date.year, tx.transaction_date.month)
                by_month[key].append(tx)
            
            # Analyze each month
            current = start_date.replace(day=1)
            while current <= end_date:
                year, month = current.year, current.month
                month_txs = by_month.get((year, month), [])
                
                flow = self._analyze_month(month_txs, categories, year, month)
                monthly_flows.append(flow)
                
                # Aggregate by category
                for cat, amount in flow.by_category.items():
                    if amount > 0:
                        expense_by_category[cat] += amount
                    else:
                        income_by_category[cat] += abs(amount)
                
                # Move to next month
                if month == 12:
                    current = date(year + 1, 1, 1)
                else:
                    current = date(year, month + 1, 1)
        
        # Calculate totals
        total_income = sum(f.income for f in monthly_flows)
        total_expenses = sum(f.total_expenses for f in monthly_flows)
        total_essential = sum(f.essential_expenses for f in monthly_flows)
        total_discretionary = sum(f.discretionary_expenses for f in monthly_flows)
        
        num_months = len(monthly_flows) or 1
        avg_income = total_income / num_months
        avg_expenses = total_expenses / num_months
        avg_savings = self._calculate_savings_rate(avg_income, avg_expenses)
        
        fcf = total_income - total_expenses
        
        return CashFlowSummary(
            analysis_period_start=start_date,
            analysis_period_end=end_date,
            total_income=total_income,
            total_expenses=total_expenses,
            total_essential=total_essential,
            total_discretionary=total_discretionary,
            average_monthly_income=avg_income,
            average_monthly_expenses=avg_expenses,
            average_savings_rate=avg_savings,
            free_cash_flow=fcf,
            monthly_flows=monthly_flows,
            expense_by_category=dict(expense_by_category),
            income_by_category=dict(income_by_category),
        )
    
    def _analyze_month(
        self,
        transactions: List[Transaction],
        categories: Dict[int, TransactionCategory],
        year: int,
        month: int
    ) -> MonthlyFlow:
        """Analyze a single month"""
        income = Decimal('0')
        essential = Decimal('0')
        discretionary = Decimal('0')
        by_category: Dict[str, Decimal] = defaultdict(Decimal)
        
        for tx in transactions:
            amount = tx.amount
            cat = categories.get(tx.category_id) if tx.category_id else None
            cat_name = cat.name if cat else 'その他'
            
            if tx.type == TransactionType.INCOME.value:
                income += amount
                by_category[cat_name] -= amount  # Negative for income
            else:
                # Expense or Depreciation
                if cat and cat.is_essential:
                    essential += amount
                else:
                    discretionary += amount
                by_category[cat_name] += amount
        
        total_expenses = essential + discretionary
        net_flow = income - total_expenses
        savings_rate = self._calculate_savings_rate(income, total_expenses)
        
        return MonthlyFlow(
            year=year,
            month=month,
            income=income,
            essential_expenses=essential,
            discretionary_expenses=discretionary,
            total_expenses=total_expenses,
            net_flow=net_flow,
            savings_rate=savings_rate,
            by_category=dict(by_category),
        )
    
    def _calculate_savings_rate(self, income: Decimal, expenses: Decimal) -> Decimal:
        """Calculate savings rate"""
        if income <= 0:
            return Decimal('0')
        savings = income - expenses
        rate = (savings / income * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        return rate
    
    def analyze_burn_rate(self, liquid_assets: Decimal, months: int = 6) -> BurnRateAnalysis:
        """
        Calculate burn rate and runway based on recent expenses.
        
        Args:
            liquid_assets: Current liquid assets (cash, easily liquidatable)
            months: Number of months to average for burn rate
        
        Returns:
            BurnRateAnalysis with runway information
        """
        # Get recent cash flow
        cf = self.analyze_cash_flow(months=months)
        monthly_burn = cf.average_monthly_expenses
        
        if monthly_burn <= 0:
            runway_months = 999  # Essentially infinite
        else:
            runway_months = int(liquid_assets / monthly_burn)
        
        runway_date = date.today() + timedelta(days=30 * runway_months)
        is_sustainable = runway_months >= 6
        
        return BurnRateAnalysis(
            monthly_burn_rate=monthly_burn,
            liquid_assets=liquid_assets,
            runway_months=runway_months,
            runway_date=runway_date,
            is_sustainable=is_sustainable,
        )
    
    def get_budget_vs_actual(
        self,
        year: int,
        month: int
    ) -> Dict[str, Dict[str, Decimal]]:
        """
        Compare actual spending to standard cost budget.
        
        Args:
            year: Year
            month: Month
        
        Returns:
            Dict of category -> {budget, actual, variance}
        """
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        days_in_month = (end_date - start_date).days + 1
        
        result = {}
        
        with Session(self.engine) as session:
            # Get budget from standard costs
            costs = session.query(StandardCostParam).all()
            
            for cost in costs:
                if cost.unit == CostUnit.PER_DAY.value:
                    budget = cost.unit_cost * days_in_month
                elif cost.unit == CostUnit.PER_MONTH.value:
                    budget = cost.unit_cost
                else:  # PER_YEAR
                    budget = cost.unit_cost / 12
                
                result[cost.category_key] = {
                    'budget': budget.quantize(Decimal('0.01')),
                    'actual': Decimal('0'),
                    'variance': Decimal('0'),
                }
            
            # Get actual spending by category
            cf = self.analyze_cash_flow(start_date=start_date, end_date=end_date)
            
            for cat, amount in cf.expense_by_category.items():
                # Try to match category to standard cost key
                matched_key = self._match_category_to_cost_key(cat)
                if matched_key and matched_key in result:
                    result[matched_key]['actual'] = amount
                    result[matched_key]['variance'] = result[matched_key]['budget'] - amount
        
        return result
    
    def _match_category_to_cost_key(self, category_name: str) -> Optional[str]:
        """Match transaction category to standard cost key"""
        mappings = {
            '食費': 'FOOD_DAILY',
            '住居費': 'RENT_MONTHLY',
            '光熱費': 'UTILITIES_MONTHLY',
            '通信費': 'COMMUNICATION_MONTHLY',
            '交通費': 'TRANSPORT_MONTHLY',
            '日用品': 'DAILY_GOODS_MONTHLY',
            '趣味・娯楽': 'ENTERTAINMENT_MONTHLY',
            '保険': 'INSURANCE_MONTHLY',
        }
        return mappings.get(category_name)
    
    def calculate_fcf(self, months: int = 3) -> Decimal:
        """
        Calculate Free Cash Flow (average over recent months).
        
        FCF = Income - Essential Expenses - Discretionary Expenses
        
        Args:
            months: Number of months to average
        
        Returns:
            Average monthly FCF
        """
        cf = self.analyze_cash_flow(months=months)
        return cf.free_cash_flow / months if months > 0 else Decimal('0')
    
    def get_trend(self, metric: str, months: int = 12) -> List[Dict]:
        """
        Get trend data for a metric over time.
        
        Args:
            metric: 'income', 'expenses', 'savings_rate', 'net_flow'
            months: Number of months to include
        
        Returns:
            List of {date, value} dicts for charting
        """
        cf = self.analyze_cash_flow(months=months)
        
        trend = []
        for flow in cf.monthly_flows:
            month_date = date(flow.year, flow.month, 1)
            
            if metric == 'income':
                value = flow.income
            elif metric == 'expenses':
                value = flow.total_expenses
            elif metric == 'savings_rate':
                value = flow.savings_rate
            elif metric == 'net_flow':
                value = flow.net_flow
            else:
                value = Decimal('0')
            
            trend.append({
                'date': month_date.isoformat(),
                'value': float(value),
            })
        
        return trend
