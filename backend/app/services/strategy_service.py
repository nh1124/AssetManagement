"""Strategy Service - Life Event calculations and goal probability."""
from sqlalchemy.orm import Session
from datetime import date
from typing import List
from .. import models


def calculate_goal_progress(
    target_amount: float,
    current_funded: float,
    monthly_contribution: float,
    months_remaining: int,
    annual_return: float = 5.0
) -> dict:
    """
    Calculate goal funding progress and probability.
    
    Progress = (Current funded + Future Value of monthly contributions) / Target
    """
    if months_remaining <= 0:
        # Goal date passed
        progress = (current_funded / target_amount * 100) if target_amount > 0 else 0
        return {
            "progress_pct": min(progress, 100),
            "projected_amount": current_funded,
            "shortfall": max(0, target_amount - current_funded),
            "probability": min(100, progress)
        }
    
    # Calculate future value of monthly contributions with compound interest
    monthly_rate = (annual_return / 100) / 12
    
    if monthly_rate > 0:
        # FV of annuity formula
        fv_contributions = monthly_contribution * (
            ((1 + monthly_rate) ** months_remaining - 1) / monthly_rate
        )
    else:
        fv_contributions = monthly_contribution * months_remaining
    
    # Future value of current funded amount
    fv_current = current_funded * ((1 + monthly_rate) ** months_remaining)
    
    projected_total = fv_current + fv_contributions
    progress_pct = (projected_total / target_amount * 100) if target_amount > 0 else 0
    
    return {
        "progress_pct": min(progress_pct, 100),
        "projected_amount": projected_total,
        "shortfall": max(0, target_amount - projected_total),
        "probability": min(100, progress_pct)
    }


def get_life_events_with_progress(db: Session, client_id: int, simulation_config: dict = None) -> List[dict]:
    """Get all life events with calculated progress for current client."""
    life_events = db.query(models.LifeEvent).filter(models.LifeEvent.client_id == client_id).all()
    
    # Get simulation config for current client
    if simulation_config is None:
        config = db.query(models.SimulationConfig).filter(models.SimulationConfig.client_id == client_id).first()
        simulation_config = {
            "annual_return": config.annual_return if config else 5.0,
            "monthly_savings": config.monthly_savings if config else 100000
        }
    
    result = []
    today = date.today()
    
    for event in life_events:
        months_remaining = (event.target_date.year - today.year) * 12 + (event.target_date.month - today.month)
        
        monthly_contrib = event.monthly_contribution or (simulation_config["monthly_savings"] / max(1, len(life_events)))
        
        progress = calculate_goal_progress(
            target_amount=event.target_amount,
            current_funded=event.funded_amount or 0,
            monthly_contribution=monthly_contrib,
            months_remaining=months_remaining,
            annual_return=simulation_config["annual_return"]
        )
        
        result.append({
            "id": event.id,
            "name": event.name,
            "target_date": event.target_date.isoformat(),
            "target_amount": event.target_amount,
            "funded_amount": event.funded_amount or 0,
            "priority": event.priority,
            "months_remaining": months_remaining,
            "monthly_contribution": monthly_contrib,
            **progress
        })
    
    return result


def calculate_overall_goal_probability(db: Session, client_id: int) -> dict:
    """Calculate overall probability of achieving all goals for current client."""
    events_with_progress = get_life_events_with_progress(db, client_id=client_id)
    
    if not events_with_progress:
        return {
            "overall_probability": 100,
            "total_goals": 0,
            "total_target": 0,
            "total_projected": 0
        }
    
    total_target = sum(e["target_amount"] for e in events_with_progress)
    total_projected = sum(e["projected_amount"] for e in events_with_progress)
    
    # Weighted average probability based on target amounts
    weighted_prob = sum(
        e["probability"] * (e["target_amount"] / total_target) 
        for e in events_with_progress
    ) if total_target > 0 else 0
    
    return {
        "overall_probability": round(weighted_prob, 1),
        "total_goals": len(events_with_progress),
        "total_target": total_target,
        "total_projected": total_projected,
        "goals": events_with_progress
    }


def generate_budget_from_goals(db: Session, month: str, client_id: int) -> List[dict]:
    """Generate a budget template derived from life event goals for current client."""
    life_events = db.query(models.LifeEvent).filter(models.LifeEvent.client_id == client_id).all()
    
    # Get simulation config for monthly savings
    config = db.query(models.SimulationConfig).filter(models.SimulationConfig.client_id == client_id).first()
    total_monthly_savings = config.monthly_savings if config else 100000
    
    budget_items = []
    
    # Allocate savings across goals based on priority
    priority_weights = {"high": 3, "medium": 2, "low": 1}
    total_weight = sum(priority_weights.get(e.priority, 1) for e in life_events) or 1
    
    for event in life_events:
        weight = priority_weights.get(event.priority, 1)
        allocation = (weight / total_weight) * total_monthly_savings
        
        budget_items.append({
            "category": f"Savings: {event.name}",
            "proposed_amount": allocation,
            "derived_from": event.name,
            "month": month
        })
    
    return budget_items
