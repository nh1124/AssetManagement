"""
Valuation Engine
Handles mark-to-market valuation, FX conversion, and logical balance calculation.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import logging

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

try:
    import yfinance as yf
except ImportError:
    yf = None

from models.schema import (
    AssetPosition,
    MarketPrice,
    ExchangeRate,
    BalanceSnapshot,
    Transaction,
    Account,
    TaxType,
)

logger = logging.getLogger(__name__)


@dataclass
class PositionValuation:
    """Valuation result for a single position"""
    position_id: int
    ticker: str
    name: str
    quantity: Decimal
    unit_price_raw: Decimal
    unit_price_jpy: Decimal
    valuation_jpy: Decimal
    cost_basis_jpy: Decimal
    unrealized_gain_jpy: Decimal
    estimated_tax_jpy: Decimal
    net_value_jpy: Decimal
    currency: str
    asset_class: str


@dataclass 
class PortfolioValuation:
    """Aggregate valuation for entire portfolio"""
    valuation_date: date
    total_valuation_jpy: Decimal
    total_cost_basis_jpy: Decimal
    total_unrealized_gain_jpy: Decimal
    total_estimated_tax_jpy: Decimal
    total_net_value_jpy: Decimal
    positions: List[PositionValuation]
    by_asset_class: Dict[str, Decimal]
    by_account: Dict[str, Decimal]


class ValuationEngine:
    """Engine for calculating asset valuations"""
    
    # Tax rate for capital gains (20.315% in Japan)
    CAPITAL_GAINS_TAX_RATE = Decimal('0.20315')
    
    def __init__(self, db_url: str = "sqlite:///data/assets.db"):
        self.engine = create_engine(db_url)
        self._fx_cache: Dict[Tuple[str, str, date], Decimal] = {}
        self._price_cache: Dict[Tuple[str, date], Decimal] = {}
    
    def valuate_portfolio(self, as_of: date = None) -> PortfolioValuation:
        """
        Calculate current valuation for all positions.
        
        Args:
            as_of: Valuation date (default: today)
        
        Returns:
            PortfolioValuation with all position valuations
        """
        as_of = as_of or date.today()
        positions = []
        by_asset_class: Dict[str, Decimal] = {}
        by_account: Dict[str, Decimal] = {}
        
        with Session(self.engine) as session:
            active_positions = session.query(AssetPosition).filter(
                AssetPosition.status == 'ACTIVE'
            ).all()
            
            for pos in active_positions:
                val = self._valuate_position(session, pos, as_of)
                positions.append(val)
                
                # Aggregate by asset class
                ac = val.asset_class
                by_asset_class[ac] = by_asset_class.get(ac, Decimal('0')) + val.net_value_jpy
                
                # Aggregate by account
                acc_name = pos.account.name if pos.account else 'Unknown'
                by_account[acc_name] = by_account.get(acc_name, Decimal('0')) + val.net_value_jpy
        
        total_valuation = sum(p.valuation_jpy for p in positions)
        total_cost = sum(p.cost_basis_jpy for p in positions)
        total_gain = sum(p.unrealized_gain_jpy for p in positions)
        total_tax = sum(p.estimated_tax_jpy for p in positions)
        total_net = sum(p.net_value_jpy for p in positions)
        
        return PortfolioValuation(
            valuation_date=as_of,
            total_valuation_jpy=total_valuation,
            total_cost_basis_jpy=total_cost,
            total_unrealized_gain_jpy=total_gain,
            total_estimated_tax_jpy=total_tax,
            total_net_value_jpy=total_net,
            positions=positions,
            by_asset_class=by_asset_class,
            by_account=by_account,
        )
    
    def _valuate_position(self, session: Session, pos: AssetPosition, as_of: date) -> PositionValuation:
        """Valuate a single position"""
        # Get current price
        if pos.asset_class.is_market_linked:
            unit_price_raw = self._get_market_price(session, pos.ticker_symbol, as_of)
        else:
            # For cash or non-market assets, use acquisition price
            unit_price_raw = pos.acquisition_price
        
        # Convert to JPY if needed
        if pos.currency_code != 'JPY':
            fx_rate = self._get_fx_rate(session, pos.currency_code, 'JPY', as_of)
            unit_price_jpy = unit_price_raw * fx_rate
        else:
            unit_price_jpy = unit_price_raw
        
        # Calculate valuation
        valuation_jpy = pos.quantity * unit_price_jpy
        cost_basis_jpy = pos.quantity * pos.acquisition_price
        
        # For foreign currency assets, convert cost basis too
        if pos.currency_code != 'JPY':
            # Use historical FX rate for cost basis (simplified: using current rate)
            cost_basis_jpy = cost_basis_jpy * self._get_fx_rate(
                session, pos.currency_code, 'JPY', pos.acquisition_date
            )
        
        unrealized_gain = valuation_jpy - cost_basis_jpy
        
        # Calculate estimated tax (only on gains, and only for taxable accounts)
        estimated_tax = Decimal('0')
        if unrealized_gain > 0 and pos.account:
            if pos.account.tax_type == TaxType.TAXABLE.value:
                estimated_tax = unrealized_gain * self.CAPITAL_GAINS_TAX_RATE
            # NISA and IDECO: no tax on gains
        
        net_value = valuation_jpy - estimated_tax
        
        return PositionValuation(
            position_id=pos.id,
            ticker=pos.ticker_symbol,
            name=pos.name,
            quantity=pos.quantity,
            unit_price_raw=unit_price_raw,
            unit_price_jpy=unit_price_jpy,
            valuation_jpy=valuation_jpy,
            cost_basis_jpy=cost_basis_jpy,
            unrealized_gain_jpy=unrealized_gain,
            estimated_tax_jpy=estimated_tax,
            net_value_jpy=net_value,
            currency=pos.currency_code,
            asset_class=pos.asset_class_code,
        )
    
    def _get_market_price(self, session: Session, ticker: str, as_of: date) -> Decimal:
        """Get market price for a ticker"""
        cache_key = (ticker, as_of)
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]
        
        # Try database first
        price_record = session.query(MarketPrice).filter(
            MarketPrice.ticker_symbol == ticker,
            MarketPrice.date <= as_of
        ).order_by(MarketPrice.date.desc()).first()
        
        if price_record:
            self._price_cache[cache_key] = price_record.close_price
            return price_record.close_price
        
        # Fetch from yfinance if available
        if yf:
            try:
                price = self._fetch_price_yfinance(session, ticker, as_of)
                if price:
                    self._price_cache[cache_key] = price
                    return price
            except Exception as e:
                logger.warning(f"Failed to fetch price for {ticker}: {e}")
        
        # Fallback to 0
        logger.warning(f"No price found for {ticker}")
        return Decimal('0')
    
    def _fetch_price_yfinance(self, session: Session, ticker: str, as_of: date) -> Optional[Decimal]:
        """Fetch price from Yahoo Finance and cache it"""
        if not yf:
            return None
        
        try:
            stock = yf.Ticker(ticker)
            # Get history for past week to handle weekends/holidays
            start = as_of - timedelta(days=7)
            hist = stock.history(start=start.isoformat(), end=(as_of + timedelta(days=1)).isoformat())
            
            if hist.empty:
                return None
            
            # Get most recent price
            close_price = Decimal(str(hist['Close'].iloc[-1]))
            price_date = hist.index[-1].date()
            
            # Save to database
            price_record = MarketPrice(
                ticker_symbol=ticker,
                date=price_date,
                close_price=close_price,
                currency_code='USD',  # Assume USD for yfinance
            )
            session.merge(price_record)
            session.commit()
            
            return close_price
        except Exception as e:
            logger.error(f"yfinance error for {ticker}: {e}")
            return None
    
    def _get_fx_rate(self, session: Session, from_curr: str, to_curr: str, as_of: date) -> Decimal:
        """Get exchange rate"""
        if from_curr == to_curr:
            return Decimal('1')
        
        cache_key = (from_curr, to_curr, as_of)
        if cache_key in self._fx_cache:
            return self._fx_cache[cache_key]
        
        # Try database
        rate_record = session.query(ExchangeRate).filter(
            ExchangeRate.from_currency == from_curr,
            ExchangeRate.to_currency == to_curr,
            ExchangeRate.date <= as_of
        ).order_by(ExchangeRate.date.desc()).first()
        
        if rate_record:
            self._fx_cache[cache_key] = rate_record.rate
            return rate_record.rate
        
        # Try fetching from yfinance
        if yf:
            try:
                rate = self._fetch_fx_yfinance(session, from_curr, to_curr, as_of)
                if rate:
                    self._fx_cache[cache_key] = rate
                    return rate
            except Exception as e:
                logger.warning(f"Failed to fetch FX rate {from_curr}/{to_curr}: {e}")
        
        # Default rates as fallback
        defaults = {
            ('USD', 'JPY'): Decimal('150'),
            ('EUR', 'JPY'): Decimal('165'),
            ('GBP', 'JPY'): Decimal('190'),
        }
        return defaults.get((from_curr, to_curr), Decimal('1'))
    
    def _fetch_fx_yfinance(self, session: Session, from_curr: str, to_curr: str, as_of: date) -> Optional[Decimal]:
        """Fetch FX rate from Yahoo Finance"""
        if not yf:
            return None
        
        try:
            ticker = f"{from_curr}{to_curr}=X"
            fx = yf.Ticker(ticker)
            start = as_of - timedelta(days=7)
            hist = fx.history(start=start.isoformat(), end=(as_of + timedelta(days=1)).isoformat())
            
            if hist.empty:
                return None
            
            rate = Decimal(str(hist['Close'].iloc[-1]))
            rate_date = hist.index[-1].date()
            
            # Save to database
            rate_record = ExchangeRate(
                from_currency=from_curr,
                to_currency=to_curr,
                date=rate_date,
                rate=rate,
            )
            session.merge(rate_record)
            session.commit()
            
            return rate
        except Exception as e:
            logger.error(f"yfinance FX error: {e}")
            return None
    
    def calculate_logical_balance(self, account_id: Optional[int] = None) -> Decimal:
        """
        Calculate logical balance (actual balance - pending liabilities).
        
        Args:
            account_id: Specific account to calculate for, or all accounts if None
        
        Returns:
            Logical balance in JPY
        """
        with Session(self.engine) as session:
            # Get current cash positions
            query = session.query(
                func.sum(AssetPosition.quantity * AssetPosition.acquisition_price)
            ).filter(
                AssetPosition.asset_class_code == 'CASH',
                AssetPosition.status == 'ACTIVE'
            )
            
            if account_id:
                query = query.filter(AssetPosition.account_id == account_id)
            
            actual_balance = query.scalar() or Decimal('0')
            
            # Get pending liabilities (future transactions marked as logical_only)
            pending_query = session.query(
                func.sum(Transaction.amount)
            ).filter(
                Transaction.is_logical_only == True,
                Transaction.transaction_date >= date.today()
            )
            
            if account_id:
                pending_query = pending_query.filter(
                    Transaction.from_account_id == account_id
                )
            
            pending_liabilities = pending_query.scalar() or Decimal('0')
            
            return actual_balance - pending_liabilities
    
    def save_snapshot(self, as_of: date = None) -> int:
        """
        Save current valuations as balance snapshots.
        
        Args:
            as_of: Snapshot date (default: today)
        
        Returns:
            Number of snapshots saved
        """
        as_of = as_of or date.today()
        portfolio = self.valuate_portfolio(as_of)
        
        count = 0
        with Session(self.engine) as session:
            for pos in portfolio.positions:
                snapshot = BalanceSnapshot(
                    date=as_of,
                    position_id=pos.position_id,
                    quantity=pos.quantity,
                    unit_price_raw=pos.unit_price_raw,
                    valuation_jpy=pos.valuation_jpy,
                    cost_basis_jpy=pos.cost_basis_jpy,
                    estimated_tax_jpy=pos.estimated_tax_jpy,
                )
                session.merge(snapshot)
                count += 1
            
            session.commit()
        
        logger.info(f"Saved {count} balance snapshots for {as_of}")
        return count
