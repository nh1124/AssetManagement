"""
Simulation Engine
Monte Carlo simulation for goal achievement probability and roadmap analysis.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional, Dict
import logging

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models.schema import LifeGoal, AssetPosition, GoalAllocation

logger = logging.getLogger(__name__)


@dataclass
class SimulationParams:
    """Parameters for Monte Carlo simulation"""
    # Return assumptions
    expected_return: float = 0.05  # 5% annual return
    volatility: float = 0.15  # 15% annual volatility
    inflation_rate: float = 0.02  # 2% annual inflation
    
    # Simulation settings
    num_simulations: int = 1000
    time_horizon_years: int = 30
    
    # Monthly contribution
    monthly_contribution: Decimal = Decimal('50000')
    contribution_growth_rate: float = 0.02  # Annual growth in contributions


@dataclass
class GoalSimulationResult:
    """Result for a single goal"""
    goal_id: int
    goal_name: str
    target_amount: Decimal
    target_date: date
    current_allocation: Decimal
    success_probability: float  # 0-100%
    median_outcome: Decimal
    percentile_10: Decimal
    percentile_90: Decimal
    monthly_contribution_needed: Decimal
    gap_analysis: str


@dataclass
class SimulationResult:
    """Overall simulation results"""
    simulation_date: date
    params: SimulationParams
    initial_investment: Decimal
    projected_values: List[float]  # Final values from all simulations
    goal_results: List[GoalSimulationResult]
    overall_success_rate: float
    roadmap_trajectory: List[Dict]  # Year-by-year median projection
    recommendations: List[str]


class SimulationEngine:
    """Monte Carlo simulation engine for financial planning"""
    
    def __init__(self, db_url: str = "sqlite:///data/assets.db"):
        self.engine = create_engine(db_url)
    
    def run_simulation(
        self,
        initial_value: Decimal,
        params: Optional[SimulationParams] = None
    ) -> SimulationResult:
        """
        Run Monte Carlo simulation.
        
        Args:
            initial_value: Starting portfolio value
            params: Simulation parameters
        
        Returns:
            SimulationResult with probabilities and projections
        """
        params = params or SimulationParams()
        
        # Run simulations
        projected_values = self._monte_carlo(
            float(initial_value),
            params
        )
        
        # Calculate roadmap trajectory (year by year median)
        trajectory = self._calculate_trajectory(float(initial_value), params)
        
        # Evaluate goals
        goal_results = self._evaluate_goals(initial_value, params, projected_values)
        
        # Calculate overall success
        if goal_results:
            overall_success = sum(g.success_probability for g in goal_results) / len(goal_results)
        else:
            overall_success = 100.0
        
        # Generate recommendations
        recommendations = self._generate_recommendations(goal_results, params)
        
        return SimulationResult(
            simulation_date=date.today(),
            params=params,
            initial_investment=initial_value,
            projected_values=projected_values,
            goal_results=goal_results,
            overall_success_rate=overall_success,
            roadmap_trajectory=trajectory,
            recommendations=recommendations,
        )
    
    def _monte_carlo(self, initial: float, params: SimulationParams) -> List[float]:
        """Run Monte Carlo simulations"""
        np.random.seed(42)  # For reproducibility
        
        n_months = params.time_horizon_years * 12
        n_sims = params.num_simulations
        
        # Monthly parameters
        monthly_return = params.expected_return / 12
        monthly_vol = params.volatility / np.sqrt(12)
        monthly_inflation = params.inflation_rate / 12
        
        # Initial contribution
        monthly_contrib = float(params.monthly_contribution)
        contrib_growth = (1 + params.contribution_growth_rate) ** (1/12) - 1
        
        final_values = []
        
        for _ in range(n_sims):
            value = initial
            contrib = monthly_contrib
            
            for month in range(n_months):
                # Random return
                random_return = np.random.normal(monthly_return, monthly_vol)
                value = value * (1 + random_return)
                
                # Add contribution
                value += contrib
                
                # Grow contribution annually
                if month > 0 and month % 12 == 0:
                    contrib *= (1 + params.contribution_growth_rate)
            
            # Adjust for inflation to get real value
            inflation_factor = (1 + params.inflation_rate) ** params.time_horizon_years
            real_value = value / inflation_factor
            
            final_values.append(real_value)
        
        return final_values
    
    def _calculate_trajectory(self, initial: float, params: SimulationParams) -> List[Dict]:
        """Calculate year-by-year median trajectory"""
        trajectory = []
        
        n_sims = min(100, params.num_simulations)  # Fewer sims for trajectory
        
        for year in range(params.time_horizon_years + 1):
            if year == 0:
                trajectory.append({
                    'year': year,
                    'date': date.today().year,
                    'value': initial,
                })
                continue
            
            # Run quick simulations for this year
            final_values = []
            n_months = year * 12
            
            for _ in range(n_sims):
                value = initial
                contrib = float(params.monthly_contribution)
                
                for month in range(n_months):
                    random_return = np.random.normal(
                        params.expected_return / 12,
                        params.volatility / np.sqrt(12)
                    )
                    value = value * (1 + random_return) + contrib
                    
                    if month > 0 and month % 12 == 0:
                        contrib *= (1 + params.contribution_growth_rate)
                
                final_values.append(value)
            
            median_value = np.median(final_values)
            trajectory.append({
                'year': year,
                'date': date.today().year + year,
                'value': float(median_value),
            })
        
        return trajectory
    
    def _evaluate_goals(
        self,
        initial_value: Decimal,
        params: SimulationParams,
        projected_values: List[float]
    ) -> List[GoalSimulationResult]:
        """Evaluate achievement probability for each goal"""
        results = []
        
        with Session(self.engine) as session:
            goals = session.query(LifeGoal).all()
            
            for goal in goals:
                # Calculate years until goal
                today = date.today()
                years_to_goal = max(0, (goal.target_date - today).days / 365)
                
                if years_to_goal <= 0:
                    # Goal is past due
                    results.append(GoalSimulationResult(
                        goal_id=goal.id,
                        goal_name=goal.name,
                        target_amount=goal.target_amount,
                        target_date=goal.target_date,
                        current_allocation=self._get_goal_allocation(session, goal.id),
                        success_probability=0.0,
                        median_outcome=Decimal('0'),
                        percentile_10=Decimal('0'),
                        percentile_90=Decimal('0'),
                        monthly_contribution_needed=Decimal('0'),
                        gap_analysis="Goal date has passed",
                    ))
                    continue
                
                # Run simulations for this specific goal timeframe
                goal_values = self._simulate_for_years(
                    float(initial_value),
                    params,
                    int(years_to_goal)
                )
                
                target = float(goal.target_amount)
                
                # Calculate success probability
                successes = sum(1 for v in goal_values if v >= target)
                probability = (successes / len(goal_values)) * 100
                
                # Calculate percentiles
                median = Decimal(str(np.median(goal_values)))
                p10 = Decimal(str(np.percentile(goal_values, 10)))
                p90 = Decimal(str(np.percentile(goal_values, 90)))
                
                # Calculate required monthly contribution for 90% success
                needed = self._calculate_required_contribution(
                    float(initial_value),
                    target,
                    years_to_goal,
                    params
                )
                
                # Gap analysis
                gap = target - float(median)
                if gap > 0:
                    gap_analysis = f"Median falls short by ¥{gap:,.0f}"
                else:
                    gap_analysis = f"On track - median exceeds target by ¥{abs(gap):,.0f}"
                
                results.append(GoalSimulationResult(
                    goal_id=goal.id,
                    goal_name=goal.name,
                    target_amount=goal.target_amount,
                    target_date=goal.target_date,
                    current_allocation=self._get_goal_allocation(session, goal.id),
                    success_probability=probability,
                    median_outcome=median,
                    percentile_10=p10,
                    percentile_90=p90,
                    monthly_contribution_needed=Decimal(str(needed)),
                    gap_analysis=gap_analysis,
                ))
        
        return results
    
    def _simulate_for_years(
        self,
        initial: float,
        params: SimulationParams,
        years: int
    ) -> List[float]:
        """Run simulations for specific number of years"""
        n_months = years * 12
        n_sims = params.num_simulations
        
        final_values = []
        
        for _ in range(n_sims):
            value = initial
            contrib = float(params.monthly_contribution)
            
            for month in range(n_months):
                random_return = np.random.normal(
                    params.expected_return / 12,
                    params.volatility / np.sqrt(12)
                )
                value = value * (1 + random_return) + contrib
                
                if month > 0 and month % 12 == 0:
                    contrib *= (1 + params.contribution_growth_rate)
            
            final_values.append(value)
        
        return final_values
    
    def _get_goal_allocation(self, session: Session, goal_id: int) -> Decimal:
        """Get current allocation for a goal"""
        allocations = session.query(GoalAllocation).filter(
            GoalAllocation.goal_id == goal_id
        ).all()
        
        total = Decimal('0')
        for alloc in allocations:
            pos = session.get(AssetPosition, alloc.position_id)
            if pos:
                total += pos.quantity * pos.acquisition_price * alloc.allocation_ratio
        
        return total
    
    def _calculate_required_contribution(
        self,
        initial: float,
        target: float,
        years: float,
        params: SimulationParams
    ) -> float:
        """Calculate monthly contribution needed to reach target with 90% probability"""
        # Use future value formula as approximation
        # FV = PV * (1+r)^n + PMT * ((1+r)^n - 1) / r
        
        monthly_rate = params.expected_return / 12
        n_months = int(years * 12)
        
        # Target with safety margin (90th percentile assumption)
        safety_margin = 1.3  # Add 30% margin
        adjusted_target = target * safety_margin
        
        # Future value of initial investment
        fv_initial = initial * ((1 + monthly_rate) ** n_months)
        
        # Required from contributions
        required_from_contributions = adjusted_target - fv_initial
        
        if required_from_contributions <= 0:
            return 0
        
        # Solve for PMT
        # PMT = FV * r / ((1+r)^n - 1)
        if monthly_rate > 0:
            factor = ((1 + monthly_rate) ** n_months - 1) / monthly_rate
            pmt = required_from_contributions / factor
        else:
            pmt = required_from_contributions / n_months
        
        return max(0, pmt)
    
    def _generate_recommendations(
        self,
        goal_results: List[GoalSimulationResult],
        params: SimulationParams
    ) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        # Check for goals at risk
        at_risk = [g for g in goal_results if g.success_probability < 70]
        on_track = [g for g in goal_results if g.success_probability >= 85]
        
        if at_risk:
            for goal in at_risk:
                if goal.monthly_contribution_needed > params.monthly_contribution:
                    diff = goal.monthly_contribution_needed - params.monthly_contribution
                    recommendations.append(
                        f"「{goal.goal_name}」達成のため、月の積立額を ¥{diff:,.0f} 増やすことを検討してください"
                    )
        
        if not recommendations:
            if on_track:
                recommendations.append("全てのゴールが順調です。現在の計画を維持してください。")
            else:
                recommendations.append("リスク許容度の見直しや、目標金額の調整を検討してください。")
        
        return recommendations
    
    def sensitivity_analysis(
        self,
        initial_value: Decimal,
        goal_amount: Decimal,
        years: int
    ) -> Dict[str, List[Dict]]:
        """
        Run sensitivity analysis on key parameters.
        
        Returns probability curves for different scenarios.
        """
        results = {
            'return_sensitivity': [],
            'contribution_sensitivity': [],
        }
        
        base_params = SimulationParams()
        
        # Sensitivity to expected return
        for return_rate in [0.02, 0.04, 0.06, 0.08, 0.10]:
            params = SimulationParams(expected_return=return_rate)
            values = self._simulate_for_years(float(initial_value), params, years)
            probability = sum(1 for v in values if v >= float(goal_amount)) / len(values) * 100
            results['return_sensitivity'].append({
                'return_rate': return_rate * 100,
                'probability': probability,
            })
        
        # Sensitivity to monthly contribution
        for contrib in [30000, 50000, 70000, 100000, 150000]:
            params = SimulationParams(monthly_contribution=Decimal(str(contrib)))
            values = self._simulate_for_years(float(initial_value), params, years)
            probability = sum(1 for v in values if v >= float(goal_amount)) / len(values) * 100
            results['contribution_sensitivity'].append({
                'contribution': contrib,
                'probability': probability,
            })
        
        return results
