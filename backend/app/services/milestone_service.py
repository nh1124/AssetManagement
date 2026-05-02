"""Milestone helpers for goal roadmaps."""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from .. import models
from .goal_service import get_life_events_with_progress


def build_default_milestone_rows(db: Session, client_id: int, life_event_id: int) -> list[dict]:
    """Build editable milestone defaults from the calculated annual roadmap.

    Annual Roadmap remains useful as a baseline calculator, but persisted milestones
    are the user-facing roadmap. The final target date is always included so the
    user has an explicit end-state milestone.
    """
    events = get_life_events_with_progress(db, client_id=client_id)
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
            }
        )

    if target_date not in seen_dates:
        rows.append(
            {
                "life_event_id": life_event_id,
                "date": target_date,
                "target_amount": float(event["target_amount"]),
                "note": "Final target",
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
