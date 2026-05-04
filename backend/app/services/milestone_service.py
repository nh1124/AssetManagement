"""Milestone helpers for goal roadmaps."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from .. import models
from .goal_service import get_life_events_with_progress
from .strategy_service import calculate_projection, get_goal_simulation_context, run_monte_carlo


INTERVAL_MONTHS = {
    "annual": 12,
    "semiannual": 6,
    "quarterly": 3,
}


def _get_event(db: Session, client_id: int, life_event_id: int) -> models.LifeEvent:
    event = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == client_id,
    ).first()
    if not event:
        raise LookupError("Life event not found")
    return event


def _simulation_value_at(
    *,
    basis: str,
    years_elapsed: float,
    context: dict,
    volatility: float,
    n_simulations: int,
) -> float:
    if basis == "deterministic":
        return calculate_projection(
            current_funded=context["current_funded"],
            monthly_savings=context["allocated_monthly_savings"],
            years_remaining=years_elapsed,
            annual_return=context["effective_return"],
        )

    result = run_monte_carlo(
        current_funded=context["current_funded"],
        monthly_savings=context["allocated_monthly_savings"],
        years_remaining=years_elapsed,
        annual_return=context["effective_return"],
        volatility=volatility,
        inflation_rate=context["inflation_rate"],
        n_simulations=n_simulations,
    )
    return float(result["percentiles"][basis])


def build_default_milestone_rows(
    db: Session,
    client_id: int,
    life_event_id: int,
    *,
    annual_return: float | None = None,
    inflation: float | None = None,
    monthly_savings: float | None = None,
    contribution_schedule: list[dict[str, Any]] | None = None,
    allocation_mode: str = "weighted",
) -> list[dict]:
    """Build editable milestone defaults from the calculated annual roadmap.

    Annual Roadmap remains useful as a baseline calculator, but persisted milestones
    are the user-facing roadmap. The final target date is always included so the
    user has an explicit end-state milestone.
    """
    events = get_life_events_with_progress(
        db,
        client_id=client_id,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=contribution_schedule,
        allocation_mode=allocation_mode,
    )
    event = next((item for item in events if item["id"] == life_event_id), None)
    if not event:
        return []

    today = date.today()
    target_date = date.fromisoformat(event["target_date"])
    rows: list[dict] = []
    seen_dates: set[date] = set()

    for row in event.get("roadmap", []):
        year = int(row.get("year") or 0)
        if year <= 0:
            continue

        milestone_date = min(today + relativedelta(years=year), target_date)
        if milestone_date in seen_dates:
            continue
        seen_dates.add(milestone_date)
        rows.append(
            {
                "life_event_id": life_event_id,
                "date": milestone_date,
                "target_amount": float(row.get("end_balance") or 0),
                "note": f"Baseline year {year}",
                "source": "annual_plan",
                "source_snapshot": {"basis": "deterministic", "year": year},
            }
        )

    if target_date not in seen_dates:
        rows.append(
            {
                "life_event_id": life_event_id,
                "date": target_date,
                "target_amount": float(event["target_amount"]),
                "note": "Final target",
                "source": "annual_plan",
                "source_snapshot": {"basis": "final_target"},
            }
        )

    return rows


def reset_milestones_from_annual_plan(
    db: Session,
    client_id: int,
    life_event_id: int,
) -> list[models.Milestone]:
    """Replace a goal's milestones with defaults derived from Annual Roadmap."""
    db.query(models.Milestone).filter(
        models.Milestone.client_id == client_id,
        models.Milestone.life_event_id == life_event_id,
    ).delete(synchronize_session=False)

    created: list[models.Milestone] = []
    for row in build_default_milestone_rows(db, client_id, life_event_id):
        milestone = models.Milestone(client_id=client_id, **row)
        db.add(milestone)
        created.append(milestone)

    db.commit()
    for milestone in created:
        db.refresh(milestone)
    return created


def preview_milestones_from_simulation(
    db: Session,
    client_id: int,
    life_event_id: int,
    *,
    basis: str = "p50",
    interval: str = "annual",
    mode: str = "replace",
    n_simulations: int = 1000,
    annual_return: float | None = None,
    inflation: float | None = None,
    monthly_savings: float | None = None,
    contribution_schedule: list[dict[str, Any]] | None = None,
    allocation_mode: str = "weighted",
) -> dict:
    """Build milestone candidates from the same normalized inputs as goal simulation."""
    if basis == "annual_plan":
        existing_count = db.query(models.Milestone).filter(
            models.Milestone.client_id == client_id,
            models.Milestone.life_event_id == life_event_id,
        ).count()
        return {
            "life_event_id": life_event_id,
            "basis": basis,
            "interval": interval,
            "mode": mode,
            "existing_count": existing_count,
            "items": build_default_milestone_rows(
                db,
                client_id,
                life_event_id,
                annual_return=annual_return,
                inflation=inflation,
                monthly_savings=monthly_savings,
                contribution_schedule=contribution_schedule,
                allocation_mode=allocation_mode,
            ),
        }

    event = _get_event(db, client_id, life_event_id)
    config = db.query(models.SimulationConfig).filter(
        models.SimulationConfig.client_id == client_id
    ).first()
    volatility = config.volatility if config else 15.0
    context = get_goal_simulation_context(
        db=db,
        client_id=client_id,
        event=event,
        annual_return=annual_return,
        inflation=inflation,
        monthly_savings=monthly_savings,
        contribution_schedule=contribution_schedule,
        allocation_mode=allocation_mode,
    )

    today = context["reference_date"]
    target_date = event.target_date
    rows_by_date: dict[date, dict] = {}
    generated_at = datetime.utcnow().isoformat()

    if interval != "target_only":
        month_step = INTERVAL_MONTHS[interval]
        cursor_months = month_step
        while True:
            milestone_date = today + relativedelta(months=cursor_months)
            if milestone_date >= target_date:
                break
            years_elapsed = max(0.0, (milestone_date - today).days / 365.25)
            target_amount = _simulation_value_at(
                basis=basis,
                years_elapsed=years_elapsed,
                context=context,
                volatility=volatility,
                n_simulations=n_simulations,
            )
            rows_by_date[milestone_date] = {
                "life_event_id": life_event_id,
                "date": milestone_date,
                "target_amount": round(float(target_amount), 0),
                "note": f"Generated from simulation {basis.upper()}",
                "source": f"simulation_{basis}",
                "source_snapshot": {
                    "basis": basis,
                    "interval": interval,
                    "mode": mode,
                    "n_simulations": n_simulations if basis != "deterministic" else None,
                    "annual_return": context["annual_return"],
                    "effective_return": context["effective_return"],
                    "inflation_rate": context["inflation_rate"],
                    "volatility": volatility,
                    "monthly_savings": context["monthly_savings"],
                    "allocated_monthly_savings": context["allocated_monthly_savings"],
                    "contribution_schedule": context["contribution_schedule"],
                    "allocation_mode": context["allocation_mode"],
                    "current_funded": context["current_funded"],
                    "generated_at": generated_at,
                },
            }
            cursor_months += month_step

    rows_by_date[target_date] = {
        "life_event_id": life_event_id,
        "date": target_date,
        "target_amount": float(event.target_amount),
        "note": f"Final target from simulation {basis.upper()} plan",
        "source": f"simulation_{basis}",
        "source_snapshot": {
            "basis": "final_target",
            "interval": interval,
            "mode": mode,
            "target_amount": event.target_amount,
            "generated_at": generated_at,
        },
    }

    existing_count = db.query(models.Milestone).filter(
        models.Milestone.client_id == client_id,
        models.Milestone.life_event_id == life_event_id,
    ).count()

    return {
        "life_event_id": life_event_id,
        "basis": basis,
        "interval": interval,
        "mode": mode,
        "existing_count": existing_count,
        "items": [rows_by_date[key] for key in sorted(rows_by_date)],
    }


def apply_milestones_from_simulation(
    db: Session,
    client_id: int,
    life_event_id: int,
    **kwargs,
) -> list[models.Milestone]:
    """Persist simulation-derived milestone candidates."""
    preview = preview_milestones_from_simulation(db, client_id, life_event_id, **kwargs)
    mode = preview["mode"]
    if mode == "replace":
        db.query(models.Milestone).filter(
            models.Milestone.client_id == client_id,
            models.Milestone.life_event_id == life_event_id,
        ).delete(synchronize_session=False)
        existing_dates: set[date] = set()
    else:
        existing_dates = {
            row[0]
            for row in db.query(models.Milestone.date).filter(
                models.Milestone.client_id == client_id,
                models.Milestone.life_event_id == life_event_id,
            ).all()
        }

    created: list[models.Milestone] = []
    for row in preview["items"]:
        if row["date"] in existing_dates:
            continue
        milestone = models.Milestone(client_id=client_id, **row)
        db.add(milestone)
        created.append(milestone)

    db.commit()
    for milestone in created:
        db.refresh(milestone)
    return created
