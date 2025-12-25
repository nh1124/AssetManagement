"""
Purchase Auditor
Smart purchase audit for high-value items with trade-off analysis.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional, List
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.schema import LifeGoal, AssetPosition


logger = logging.getLogger(__name__)


class AuditDecision(str, Enum):
    """Purchase recommendation"""
    GO = "GO"  # Proceed with purchase
    WAIT = "WAIT"  # Delay purchase
    STOP = "STOP"  # Do not purchase


@dataclass
class TradeOff:
    """Trade-off impact for a single goal"""
    goal_name: str
    current_probability: float
    new_probability: float
    probability_change: float
    impact_description: str


@dataclass
class AuditResult:
    """Result of purchase audit"""
    # Input
    item_name: str
    purchase_price: Decimal
    lifespan_years: float
    resale_value: Decimal
    
    # Costs
    daily_cost: Decimal
    monthly_cost: Decimal
    annual_cost: Decimal
    true_cost: Decimal  # Price - Resale
    
    # Impact
    runway_impact_months: float
    asset_life_impact_days: int
    trade_offs: List[TradeOff]
    
    # Decision
    decision: AuditDecision
    decision_reason: str
    alternative_suggestions: List[str]


# Asset Recognition Threshold
RECOGNITION_THRESHOLD = Decimal('30000')


class PurchaseAuditor:
    """Audits high-value purchase decisions"""
    
    def __init__(self, db_url: str = "sqlite:///data/assets.db"):
        self.engine = create_engine(db_url)
    
    def audit_purchase(
        self,
        item_name: str,
        price: Decimal,
        lifespan_years: float = 5.0,
        resale_value: Optional[Decimal] = None,
        current_liquid_assets: Optional[Decimal] = None,
        monthly_expenses: Optional[Decimal] = None,
    ) -> AuditResult:
        """
        Audit a potential purchase decision.
        
        Args:
            item_name: Name of the item
            price: Purchase price in JPY
            lifespan_years: Expected useful life
            resale_value: Expected resale/salvage value (default: 10% of price)
            current_liquid_assets: Current liquid assets for runway calculation
            monthly_expenses: Monthly burn rate
        
        Returns:
            AuditResult with recommendation
        """
        # Defaults
        if resale_value is None:
            resale_value = (price * Decimal('0.1')).quantize(Decimal('1'))
        
        if current_liquid_assets is None:
            current_liquid_assets = Decimal('1000000')  # Default 1M yen
        
        if monthly_expenses is None:
            monthly_expenses = Decimal('200000')  # Default 200k yen
        
        # Calculate costs
        lifespan_days = int(lifespan_years * 365)
        true_cost = price - resale_value
        daily_cost = (true_cost / lifespan_days).quantize(Decimal('0.01'), ROUND_HALF_UP)
        monthly_cost = (daily_cost * 30).quantize(Decimal('1'))
        annual_cost = (daily_cost * 365).quantize(Decimal('1'))
        
        # Calculate runway impact
        current_runway = float(current_liquid_assets / monthly_expenses) if monthly_expenses > 0 else 999
        new_liquid = current_liquid_assets - price
        new_runway = float(new_liquid / monthly_expenses) if monthly_expenses > 0 else 999
        runway_impact = current_runway - new_runway
        
        # Calculate asset life impact (days of savings this costs)
        # Assuming 20% savings rate
        savings_per_day = float(monthly_expenses) * 0.20 / 30
        if savings_per_day > 0:
            asset_life_impact = int(float(price) / savings_per_day)
        else:
            asset_life_impact = 0
        
        # Calculate goal trade-offs
        trade_offs = self._calculate_trade_offs(price)
        
        # Make decision
        decision, reason = self._make_decision(
            price=price,
            daily_cost=daily_cost,
            runway_impact=runway_impact,
            trade_offs=trade_offs,
            new_runway=new_runway,
        )
        
        # Generate alternatives
        alternatives = self._generate_alternatives(
            item_name,
            price,
            decision,
            daily_cost,
        )
        
        return AuditResult(
            item_name=item_name,
            purchase_price=price,
            lifespan_years=lifespan_years,
            resale_value=resale_value,
            daily_cost=daily_cost,
            monthly_cost=monthly_cost,
            annual_cost=annual_cost,
            true_cost=true_cost,
            runway_impact_months=runway_impact,
            asset_life_impact_days=asset_life_impact,
            trade_offs=trade_offs,
            decision=decision,
            decision_reason=reason,
            alternative_suggestions=alternatives,
        )
    
    def _calculate_trade_offs(self, purchase_price: Decimal) -> List[TradeOff]:
        """Calculate impact on each goal"""
        trade_offs = []
        
        with Session(self.engine) as session:
            goals = session.query(LifeGoal).all()
            
            for goal in goals:
                # Simple impact calculation
                # Assuming the purchase delays saving for this goal
                
                # Calculate how much this delays the goal
                # Rough estimate: price / monthly_savings = months delayed
                # Which reduces probability by approximately X%
                
                target = float(goal.target_amount)
                if target <= 0:
                    continue
                
                # Impact as percentage of goal
                impact_pct = float(purchase_price) / target * 100
                
                # Rough probability reduction
                prob_reduction = min(impact_pct * 0.5, 20)  # Cap at 20% reduction
                
                if prob_reduction > 1:  # Only show significant impacts
                    trade_offs.append(TradeOff(
                        goal_name=goal.name,
                        current_probability=85.0,  # Placeholder
                        new_probability=85.0 - prob_reduction,
                        probability_change=-prob_reduction,
                        impact_description=f"達成確率が約{prob_reduction:.1f}%低下する可能性があります",
                    ))
        
        return trade_offs
    
    def _make_decision(
        self,
        price: Decimal,
        daily_cost: Decimal,
        runway_impact: float,
        trade_offs: List[TradeOff],
        new_runway: float,
    ) -> tuple[AuditDecision, str]:
        """Make purchase recommendation"""
        
        # Check if below recognition threshold
        if price < RECOGNITION_THRESHOLD:
            return (
                AuditDecision.GO,
                f"購入価格が資産計上基準（¥{RECOGNITION_THRESHOLD:,}）未満のため、通常の支出として処理できます。"
            )
        
        # Check runway
        if new_runway < 3:
            return (
                AuditDecision.STOP,
                f"購入後の生活防衛資金が3ヶ月未満（{new_runway:.1f}ヶ月）になります。流動性リスクが高すぎます。"
            )
        
        if new_runway < 6:
            return (
                AuditDecision.WAIT,
                f"購入後の生活防衛資金が6ヶ月未満（{new_runway:.1f}ヶ月）になります。もう少し貯蓄を増やしてからの購入を推奨します。"
            )
        
        # Check goal impacts
        severe_impacts = [t for t in trade_offs if t.probability_change < -10]
        if severe_impacts:
            goal_names = ', '.join(t.goal_name for t in severe_impacts)
            return (
                AuditDecision.WAIT,
                f"「{goal_names}」の達成確率に大きな影響（10%以上の低下）があります。目標を見直すか、購入を延期してください。"
            )
        
        # Check daily cost reasonableness
        if daily_cost > Decimal('500'):  # Over 500 yen/day
            return (
                AuditDecision.WAIT,
                f"日割りコスト（¥{daily_cost:,}/日）が高めです。本当に必要か再検討してください。"
            )
        
        # All checks passed
        return (
            AuditDecision.GO,
            f"財務的な観点から問題ありません。日割りコスト ¥{daily_cost:,}/日 は許容範囲内です。"
        )
    
    def _generate_alternatives(
        self,
        item_name: str,
        price: Decimal,
        decision: AuditDecision,
        daily_cost: Decimal,
    ) -> List[str]:
        """Generate alternative suggestions"""
        alternatives = []
        
        if decision != AuditDecision.GO:
            # Suggest cheaper alternatives
            cheaper_price = price * Decimal('0.7')
            alternatives.append(f"予算を¥{cheaper_price:,.0f}に抑えた代替品を検討")
            
            # Suggest waiting
            alternatives.append("3-6ヶ月待って、セールや型落ちを狙う")
            
            # Suggest saving more first
            monthly_save = price / 6
            alternatives.append(f"月¥{monthly_save:,.0f}を6ヶ月貯めてから購入")
        
        if daily_cost > Decimal('300'):
            # Suggest rental/subscription
            alternatives.append("レンタルやサブスクリプションの利用を検討")
        
        if not alternatives:
            alternatives.append("購入を進めて問題ありません")
        
        return alternatives
    
    def quick_check(self, price: Decimal) -> dict:
        """Quick check if purchase is within recognition threshold"""
        is_above_threshold = price >= RECOGNITION_THRESHOLD
        
        return {
            'price': float(price),
            'threshold': float(RECOGNITION_THRESHOLD),
            'requires_audit': is_above_threshold,
            'message': (
                "資産計上対象です。詳細な監査を実施してください。"
                if is_above_threshold else
                "資産計上基準未満の通常支出です。"
            )
        }
    
    def compare_options(
        self,
        options: List[dict],
        current_liquid_assets: Decimal,
        monthly_expenses: Decimal,
    ) -> List[AuditResult]:
        """
        Compare multiple purchase options.
        
        Args:
            options: List of dicts with 'name', 'price', 'lifespan_years', 'resale_value'
        
        Returns:
            List of AuditResults sorted by recommendation
        """
        results = []
        
        for opt in options:
            result = self.audit_purchase(
                item_name=opt['name'],
                price=Decimal(str(opt['price'])),
                lifespan_years=opt.get('lifespan_years', 5.0),
                resale_value=Decimal(str(opt.get('resale_value', 0))) if opt.get('resale_value') else None,
                current_liquid_assets=current_liquid_assets,
                monthly_expenses=monthly_expenses,
            )
            results.append(result)
        
        # Sort by decision (GO first) then by daily cost
        decision_order = {AuditDecision.GO: 0, AuditDecision.WAIT: 1, AuditDecision.STOP: 2}
        results.sort(key=lambda r: (decision_order[r.decision], r.daily_cost))
        
        return results
