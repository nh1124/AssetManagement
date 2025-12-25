"""
Depreciation Engine
Calculates depreciation for durable assets (TCO management).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.schema import (
    AssetPosition,
    Transaction,
    TransactionType,
    AssetStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class DepreciationSchedule:
    """Depreciation schedule for a single asset"""
    position_id: int
    asset_name: str
    acquisition_date: date
    acquisition_price: Decimal
    salvage_value: Decimal
    lifespan_days: int
    daily_depreciation: Decimal
    current_book_value: Decimal
    accumulated_depreciation: Decimal
    remaining_days: int
    replacement_date: date
    is_fully_depreciated: bool


@dataclass
class DepreciationSummary:
    """Summary of depreciation across all assets"""
    total_acquisition_value: Decimal
    total_current_book_value: Decimal
    total_accumulated_depreciation: Decimal
    monthly_depreciation_expense: Decimal
    assets_requiring_replacement: List[DepreciationSchedule]
    schedules: List[DepreciationSchedule]


class DepreciationEngine:
    """Engine for calculating asset depreciation"""
    
    def __init__(self, db_url: str = "sqlite:///data/assets.db"):
        self.engine = create_engine(db_url)
    
    def calculate_depreciation(self, as_of: date = None) -> DepreciationSummary:
        """
        Calculate depreciation for all depreciable assets.
        
        Args:
            as_of: Calculation date (default: today)
        
        Returns:
            DepreciationSummary with all asset schedules
        """
        as_of = as_of or date.today()
        schedules = []
        
        with Session(self.engine) as session:
            # Get all active depreciable assets
            assets = session.query(AssetPosition).join(
                AssetPosition.asset_class
            ).filter(
                AssetPosition.status == AssetStatus.ACTIVE.value,
                AssetPosition.lifespan_days.isnot(None),
                AssetPosition.lifespan_days > 0,
            ).all()
            
            for asset in assets:
                schedule = self._calculate_asset_depreciation(asset, as_of)
                schedules.append(schedule)
        
        # Calculate aggregates
        total_acquisition = sum(s.acquisition_price for s in schedules)
        total_book_value = sum(s.current_book_value for s in schedules)
        total_accumulated = sum(s.accumulated_depreciation for s in schedules)
        monthly_expense = sum(s.daily_depreciation * 30 for s in schedules)
        
        # Find assets needing replacement (within 90 days or already fully depreciated)
        replacement_threshold = as_of + timedelta(days=90)
        needing_replacement = [
            s for s in schedules 
            if s.is_fully_depreciated or s.replacement_date <= replacement_threshold
        ]
        
        return DepreciationSummary(
            total_acquisition_value=total_acquisition,
            total_current_book_value=total_book_value,
            total_accumulated_depreciation=total_accumulated,
            monthly_depreciation_expense=monthly_expense,
            assets_requiring_replacement=needing_replacement,
            schedules=schedules,
        )
    
    def _calculate_asset_depreciation(self, asset: AssetPosition, as_of: date) -> DepreciationSchedule:
        """Calculate depreciation for a single asset using straight-line method"""
        acquisition_price = asset.acquisition_price * asset.quantity
        salvage_value = asset.salvage_value or Decimal('0')
        lifespan_days = asset.lifespan_days
        
        # Calculate daily depreciation (straight-line)
        depreciable_amount = acquisition_price - salvage_value
        daily_depreciation = (depreciable_amount / lifespan_days).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # Calculate days elapsed
        days_elapsed = (as_of - asset.acquisition_date).days
        days_elapsed = max(0, days_elapsed)  # Can't be negative
        
        # Calculate accumulated depreciation
        accumulated = min(
            daily_depreciation * days_elapsed,
            depreciable_amount  # Cap at depreciable amount
        )
        
        # Current book value
        current_book_value = max(acquisition_price - accumulated, salvage_value)
        
        # Remaining days
        remaining_days = max(0, lifespan_days - days_elapsed)
        
        # Replacement date
        replacement_date = asset.acquisition_date + timedelta(days=lifespan_days)
        
        # Is fully depreciated?
        is_fully_depreciated = remaining_days == 0 or current_book_value <= salvage_value
        
        return DepreciationSchedule(
            position_id=asset.id,
            asset_name=asset.name,
            acquisition_date=asset.acquisition_date,
            acquisition_price=acquisition_price,
            salvage_value=salvage_value,
            lifespan_days=lifespan_days,
            daily_depreciation=daily_depreciation,
            current_book_value=current_book_value,
            accumulated_depreciation=accumulated,
            remaining_days=remaining_days,
            replacement_date=replacement_date,
            is_fully_depreciated=is_fully_depreciated,
        )
    
    def generate_depreciation_transactions(
        self,
        month: int,
        year: int,
        commit: bool = True
    ) -> List[Transaction]:
        """
        Generate monthly depreciation expense transactions.
        
        This creates DEPRECIATION type transactions for P/L impact,
        reflecting the true cost of asset ownership.
        
        Args:
            month: Month (1-12)
            year: Year
            commit: Whether to commit to database
        
        Returns:
            List of generated transactions
        """
        # Calculate for end of month
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        month_end = next_month - timedelta(days=1)
        month_start = date(year, month, 1)
        days_in_month = (next_month - month_start).days
        
        transactions = []
        
        with Session(self.engine) as session:
            # Get all depreciable assets
            assets = session.query(AssetPosition).filter(
                AssetPosition.status == AssetStatus.ACTIVE.value,
                AssetPosition.lifespan_days.isnot(None),
                AssetPosition.acquisition_date <= month_end,
            ).all()
            
            for asset in assets:
                schedule = self._calculate_asset_depreciation(asset, month_end)
                
                # Skip if fully depreciated before this month
                if schedule.replacement_date < month_start:
                    continue
                
                # Calculate this month's depreciation
                monthly_depreciation = schedule.daily_depreciation * days_in_month
                
                # Check for existing transaction
                existing = session.query(Transaction).filter(
                    Transaction.type == TransactionType.DEPRECIATION.value,
                    Transaction.asset_position_id == asset.id,
                    Transaction.transaction_date >= month_start,
                    Transaction.transaction_date <= month_end,
                ).first()
                
                if existing:
                    continue
                
                # Create depreciation transaction
                tx = Transaction(
                    transaction_date=month_end,
                    type=TransactionType.DEPRECIATION.value,
                    from_account_id=asset.account_id,
                    amount=monthly_depreciation,
                    currency_code='JPY',
                    description=f"減価償却: {asset.name} ({year}/{month:02d})",
                    asset_position_id=asset.id,
                    is_logical_only=True,  # Not actual cash movement
                )
                
                if commit:
                    session.add(tx)
                transactions.append(tx)
            
            if commit:
                session.commit()
        
        logger.info(f"Generated {len(transactions)} depreciation transactions for {year}/{month:02d}")
        return transactions
    
    def get_daily_cost(self, position_id: int) -> Decimal:
        """Get daily ownership cost for an asset"""
        with Session(self.engine) as session:
            asset = session.get(AssetPosition, position_id)
            if not asset or not asset.lifespan_days:
                return Decimal('0')
            
            schedule = self._calculate_asset_depreciation(asset, date.today())
            return schedule.daily_depreciation
    
    def estimate_replacement_cost(self, years_ahead: int = 5) -> Decimal:
        """
        Estimate total replacement cost for assets expiring within N years.
        
        Args:
            years_ahead: Number of years to look ahead
        
        Returns:
            Total estimated replacement cost
        """
        cutoff_date = date.today() + timedelta(days=365 * years_ahead)
        summary = self.calculate_depreciation()
        
        total = Decimal('0')
        for schedule in summary.schedules:
            if schedule.replacement_date <= cutoff_date:
                # Assume replacement at same cost (could add inflation factor)
                total += schedule.acquisition_price
        
        return total
