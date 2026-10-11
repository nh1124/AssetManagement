from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models, schemas
from .strategy_service import (
    calculate_goal_probability_monte_carlo,
    calculate_projection,
    get_goal_simulation_context,
    run_monte_carlo,
)


class ScenarioNameConflict(ValueError):
    pass


class ScenarioGoalMismatch(ValueError):
    pass


def _ensure_life_event(db: Session, client_id: int, life_event_id: int) -> models.LifeEvent:
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == client_id,
    ).first()
    if not event:
        raise LookupError("Life event not found")
    return event


def get_scenario(
    db: Session, client_id: int, scenario_id: int,
) -> models.SimulationScenario | None:
    return db.query(models.SimulationScenario).filter(
        models.SimulationScenario.id == scenario_id,
        models.SimulationScenario.client_id == client_id,
    ).first()


def list_scenarios(
    db: Session, client_id: int, life_event_id: int | None = None,
) -> list[models.SimulationScenario]:
    query = db.query(models.SimulationScenario).filter(
        models.SimulationScenario.client_id == client_id,
    )
    if life_event_id is not None:
        _ensure_life_event(db, client_id, life_event_id)
        query = query.filter(models.SimulationScenario.life_event_id == life_event_id)
    return query.order_by(
        models.SimulationScenario.created_at.desc(), models.SimulationScenario.id.desc(),
    ).all()


def create_scenario(
    db: Session, client_id: int, payload: schemas.SimulationScenarioCreate,
    *, commit: bool = True,
) -> models.SimulationScenario:
    _ensure_life_event(db, client_id, payload.life_event_id)
    duplicate = db.query(models.SimulationScenario).filter(
        models.SimulationScenario.client_id == client_id,
        models.SimulationScenario.life_event_id == payload.life_event_id,
        models.SimulationScenario.name == payload.name,
    ).first()
    if duplicate:
        raise ScenarioNameConflict("A scenario with that name already exists for this goal")
    scenario = models.SimulationScenario(**payload.model_dump(), client_id=client_id)
    db.add(scenario)
    if commit:
        db.commit()
        db.refresh(scenario)
    else:
        db.flush()
    return scenario


def update_scenario(
    db: Session, client_id: int, scenario_id: int, patch: schemas.SimulationScenarioUpdate,
    *, commit: bool = True,
) -> models.SimulationScenario | None:
    scenario = get_scenario(db, client_id, scenario_id)
    if scenario is None:
        return None
    for field, value in patch.model_dump(exclude_none=True).items():
        setattr(scenario, field, value)
    if commit:
        db.commit()
        db.refresh(scenario)
    else:
        db.flush()
    return scenario


def delete_scenario(
    db: Session, client_id: int, scenario_id: int, *, commit: bool = True,
) -> models.SimulationScenario | None:
    scenario = get_scenario(db, client_id, scenario_id)
    if scenario is None:
        return None
    db.delete(scenario)
    if commit:
        db.commit()
    else:
        db.flush()
    return scenario


def compare_scenarios(
    db: Session, client_id: int, payload: schemas.SimulationScenarioCompareRequest,
) -> list[dict]:
    event = _ensure_life_event(db, client_id, payload.life_event_id)

    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()
    volatility = config.volatility if config else 15.0

    items: list[dict] = []
    for scenario_id in payload.scenario_ids:
        scenario = get_scenario(db, client_id, scenario_id)
        if scenario is None:
            raise LookupError("Scenario not found")
        if scenario.life_event_id != event.id:
            raise ScenarioGoalMismatch(f"Scenario {scenario_id} does not belong to life_event {event.id}")
        context = get_goal_simulation_context(
            db,
            client_id,
            event,
            annual_return=scenario.annual_return,
            inflation=scenario.inflation,
            monthly_savings=scenario.monthly_savings,
            contribution_schedule=list(scenario.contribution_schedule or []),
            allocation_mode=scenario.allocation_mode,
        )
        mc = run_monte_carlo(
            current_funded=context["current_funded"],
            monthly_savings=context["allocated_monthly_savings"],
            years_remaining=context["years_remaining"],
            annual_return=context["effective_return"],
            volatility=volatility,
            inflation_rate=context["inflation_rate"],
            n_simulations=1000,
        )
        probability = calculate_goal_probability_monte_carlo(
            current_funded=context["current_funded"],
            monthly_savings=context["allocated_monthly_savings"],
            years_remaining=context["years_remaining"],
            target_amount=event.target_amount,
            annual_return=context["effective_return"],
            volatility=volatility,
            inflation_rate=context["inflation_rate"],
            n_simulations=1000,
        )

        years_remaining = context["years_remaining"]
        full_years = int(years_remaining)
        deterministic_yearly: list[dict] = []
        for year in range(0, full_years + 1):
            balance = calculate_projection(
                current_funded=context["current_funded"],
                monthly_savings=context["allocated_monthly_savings"],
                years_remaining=float(year),
                annual_return=context["effective_return"],
            )
            deterministic_yearly.append({"year": year, "end_balance": round(float(balance), 0)})
        if years_remaining - full_years > 0:
            balance = calculate_projection(
                current_funded=context["current_funded"],
                monthly_savings=context["allocated_monthly_savings"],
                years_remaining=years_remaining,
                annual_return=context["effective_return"],
            )
            deterministic_yearly.append(
                {"year": round(years_remaining, 2), "end_balance": round(float(balance), 0)}
            )

        items.append(
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "target_amount": event.target_amount,
                "years_remaining": round(years_remaining, 2),
                "probability": probability,
                "percentiles": mc["percentiles"],
                "year_by_year": mc["year_by_year"],
                "deterministic_yearly": deterministic_yearly,
            }
        )

    return items
