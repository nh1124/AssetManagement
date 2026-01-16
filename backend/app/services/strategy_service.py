"""Strategy Service - Life Event calculations, projections, and goal probability."""
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional, Tuple
from .. import models


def calculate_current_funded_and_weighted_return(event: models.LifeEvent) -> Tuple[float, float]:
    """
    Calculate current funded amount and weighted average return from allocations.
    Returns (current_funded, weighted_return_rate).
    """
    total_funded = 0.0
    weighted_return_sum = 0.0
    total_allocation = 0.0
    
    for alloc in event.allocations:
        if alloc.account and alloc.account.balance:
            allocation_pct = alloc.allocation_percentage / 100.0
            funded_amount = alloc.account.balance * allocation_pct
            total_funded += funded_amount
            
            # Weight the return by the funded amount
            account_return = alloc.account.expected_return or 0.0
            weighted_return_sum += funded_amount * account_return
            total_allocation += funded_amount
    
    # Calculate weighted average return
    if total_allocation > 0:
        weighted_return = weighted_return_sum / total_allocation
    else:
        weighted_return = 5.0  # Default fallback
    
    return total_funded, weighted_return


def calculate_current_funded(event: models.LifeEvent) -> float:
    """Calculate current funded amount from allocations."""
    total, _ = calculate_current_funded_and_weighted_return(event)
    return total



def calculate_projection(
    current_funded: float,
    monthly_savings: float,
    years_remaining: float,
    annual_return: float = 5.0
) -> float:
    """
    Calculate projected future value using the loop-based 'Roadmap' logic.
    Year End Balance = (Start Balance + Annual Contribution) * (1 + Annual Return Rate)
    """
    if years_remaining <= 0:
        return current_funded
    
    r = annual_return / 100.0
    balance = current_funded
    annual_contribution = monthly_savings * 12
    
    full_years = int(years_remaining)
    partial_year = years_remaining - full_years
    
    # Loop through full years
    for _ in range(full_years):
        balance = (balance + annual_contribution) * (1 + r)
        
    # Add partial year if any
    if partial_year > 0:
        balance = (balance + annual_contribution * partial_year) * (1 + r * partial_year)
        
    return balance


def generate_roadmap(
    current_funded: float,
    monthly_savings: float,
    years_remaining: float,
    annual_return: float = 5.0,
    target_amount: float = 0.0
) -> List[dict]:
    """Generate year-by-year simulation data."""
    roadmap = []
    r = annual_return / 100.0
    balance = current_funded
    annual_contribution = monthly_savings * 12
    
    # Year 0 (Current)
    roadmap.append({
        "year": 0,
        "start_balance": round(balance, 2),
        "contribution": 0,
        "investment_gain": 0,
        "end_balance": round(balance, 2),
        "goal_coverage": round((balance / target_amount * 100) if target_amount > 0 else 0, 1)
    })
    
    full_years = int(years_remaining)
    for y in range(1, full_years + 1):
        start_bal = balance
        # Year End Balance = (Start Balance + Annual Contribution) * (1 + Annual Return Rate)
        end_bal = (start_bal + annual_contribution) * (1 + r)
        gain = end_bal - start_bal - annual_contribution
        
        balance = end_bal
        roadmap.append({
            "year": y,
            "start_balance": round(start_bal, 2),
            "contribution": round(annual_contribution, 2),
            "investment_gain": round(gain, 2),
            "end_balance": round(end_bal, 2),
            "goal_coverage": round((end_bal / target_amount * 100) if target_amount > 0 else 0, 1)
        })
        
    return roadmap


def determine_status(projected: float, target: float, years_remaining: float) -> str:
    """Determine goal status based on projection vs target."""
    if years_remaining <= 0:
        if projected >= target:
            return "Achieved"
        return "Missed"
    
    ratio = projected / target if target > 0 else 0
    if ratio >= 1.0:
        return "On Track"
    elif ratio >= 0.7:
        return "At Risk"
    else:
        return "Off Track"


def get_life_events_with_progress(
    db: Session, 
    client_id: int, 
    annual_return: float = 5.0,
    monthly_savings: float = 50000.0
) -> List[dict]:
    """Get all life events with calculated progress for current client."""
    life_events = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id
    ).all()
    
    # Get simulation config for defaults
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()
    
    if config:
        annual_return = config.annual_return or annual_return
        monthly_savings = config.monthly_savings or monthly_savings
    
    today = date.today()
    result = []
    
    for event in life_events:
        # Calculate years remaining
        days_remaining = (event.target_date - today).days
        years_remaining = max(0, days_remaining / 365.25)
        
        # Calculate current funded AND weighted return from allocations
        current_funded, weighted_return = calculate_current_funded_and_weighted_return(event)
        
        # Use weighted return if allocations exist, otherwise fallback to global
        effective_return = weighted_return if event.allocations else annual_return
        
        # Calculate projected amount
        # Distribute monthly savings by priority weight
        priority_weight = {1: 3, 2: 2, 3: 1}.get(event.priority, 1)
        allocated_savings = monthly_savings * (priority_weight / 6.0)  # Simple weighting
        
        projected = calculate_projection(
            current_funded=current_funded,
            monthly_savings=allocated_savings,
            years_remaining=years_remaining,
            annual_return=effective_return
        )
        
        gap = event.target_amount - projected
        status = determine_status(projected, event.target_amount, years_remaining)
        progress_pct = (projected / event.target_amount * 100) if event.target_amount > 0 else 0
        
        # Build allocations list with expected_return
        allocations = []
        for alloc in event.allocations:
            allocations.append({
                "id": alloc.id,
                "life_event_id": alloc.life_event_id,
                "account_id": alloc.account_id,
                "allocation_percentage": alloc.allocation_percentage,
                "account_name": alloc.account.name if alloc.account else None,
                "account_balance": alloc.account.balance if alloc.account else 0,
                "expected_return": alloc.account.expected_return if alloc.account else 0
            })
        
        # Generate roadmap
        roadmap = generate_roadmap(
            current_funded=current_funded,
            monthly_savings=allocated_savings,
            years_remaining=years_remaining,
            annual_return=effective_return,
            target_amount=event.target_amount
        )
        
        result.append({
            "id": event.id,
            "name": event.name,
            "target_date": event.target_date.isoformat(),
            "target_amount": event.target_amount,
            "priority": event.priority,
            "note": event.note,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "allocations": allocations,
            "current_funded": round(current_funded, 2),
            "projected_amount": round(projected, 2),
            "gap": round(gap, 2),
            "weighted_return": round(effective_return, 2),
            "status": status,
            "progress_percentage": round(min(progress_pct, 100), 1),
            "years_remaining": round(years_remaining, 1),
            "roadmap": roadmap
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
            "total_projected": 0,
            "goals": []
        }
    
    total_target = sum(e["target_amount"] for e in events_with_progress)
    total_projected = sum(e["projected_amount"] for e in events_with_progress)
    
    # Weighted average probability based on target amounts
    weighted_prob = sum(
        e["progress_percentage"] * (e["target_amount"] / total_target) 
        for e in events_with_progress
    ) if total_target > 0 else 0
    
    return {
        "overall_probability": round(min(weighted_prob, 100), 1),
        "total_goals": len(events_with_progress),
        "total_target": total_target,
        "total_projected": round(total_projected, 2),
        "goals": events_with_progress
    }


def get_strategy_dashboard(
    db: Session, 
    client_id: int,
    annual_return: float = 5.0,
    inflation: float = 2.0,
    monthly_savings: float = 50000.0
) -> dict:
    """Get comprehensive strategy dashboard with events and unallocated assets."""
    
    # Get events with progress
    events = get_life_events_with_progress(
        db, client_id, annual_return, monthly_savings
    )
    
    # Get all asset accounts
    asset_accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "asset"
    ).all()
    
    # Calculate total allocation percentage per account
    account_allocation_map = {}
    for event in events:
        for alloc in event.get("allocations", []):
            acc_id = alloc["account_id"]
            account_allocation_map[acc_id] = account_allocation_map.get(acc_id, 0) + alloc["allocation_percentage"]
    
    # Build available assets list (any account with < 100% allocated)
    unallocated_assets = []
    total_unallocated = 0.0
    total_allocated = 0.0
    
    for acc in asset_accounts:
        used_pct = account_allocation_map.get(acc.id, 0)
        remaining_pct = max(0, 100 - used_pct)
        
        # Calculate unallocated balance portion
        balance = acc.balance or 0
        unallocated_balance = balance * (remaining_pct / 100.0)
        
        total_allocated += (balance - unallocated_balance)
        total_unallocated += unallocated_balance
        
        if remaining_pct > 0.01: # Threshold to avoid floating point issues
            unallocated_assets.append({
                "id": acc.id,
                "name": acc.name,
                "balance": balance,
                "remaining_percentage": remaining_pct,
                "available_balance": unallocated_balance
            })
    
    return {
        "events": events,
        "unallocated_assets": unallocated_assets,
        "total_allocated": round(total_allocated, 2),
        "total_unallocated": round(total_unallocated, 2),
        "simulation_params": {
            "annual_return": annual_return,
            "inflation": inflation,
            "monthly_savings": monthly_savings
        }
    }


def generate_budget_from_goals(db: Session, month: str, client_id: int) -> List[dict]:
    """Generate a budget template derived from life event goals for current client."""
    life_events = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id
    ).all()
    
    # Get simulation config for monthly savings
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()
    total_monthly_savings = config.monthly_savings if config else 100000
    
    budget_items = []
    
    # Allocate savings across goals based on priority
    priority_weights = {1: 3, 2: 2, 3: 1}
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
