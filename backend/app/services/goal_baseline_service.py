"""The goal's baseline: its projection frozen at adoption, and actual net worth against it.

A baseline is captured when a scenario becomes the goal, or when the user asks
for it (from the goal page, or while reflecting the goal into the budget). It is
never recomputed afterwards, so the difference from actual net worth shows how
reality has moved away from the plan that was chosen, not from today's edits.

Actual net worth is the month-end balance sheet of active accounts -- the same
basis the projection starts from. Months closed in 月次の締め are final; open
months, including the current one (valued at today), are provisional.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy.orm import Session

from .. import models
from .life_scenario_scope import get_goal
from .life_scenario_service import project
from .period_close_service import list_closes
from .reporting_service import get_balance_sheet

REASONS = {"adopted", "reflection", "manual"}
MAX_MONTHS = 120


def current(db: Session, client_id: int) -> models.GoalBaseline | None:
    return db.query(models.GoalBaseline).filter_by(client_id=client_id, is_current=True).first()


def history(db: Session, client_id: int) -> list[dict]:
    rows = db.query(models.GoalBaseline).filter_by(client_id=client_id).order_by(
        models.GoalBaseline.created_at.desc(), models.GoalBaseline.id.desc(),
    ).all()
    return [_describe(row) for row in rows]


def _describe(row: models.GoalBaseline) -> dict:
    return {
        "id": row.id, "scenario_id": row.scenario_id, "scenario_name": row.scenario_name,
        "reason": row.reason, "anchor_date": row.anchor_date.isoformat(), "is_current": row.is_current,
        "assumptions": row.assumptions, "events": row.events,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def capture(db: Session, client_id: int, reason: str, *, today: date | None = None) -> models.GoalBaseline | None:
    """Freeze the current goal's projection as the new baseline; the caller commits."""
    if reason not in REASONS:
        raise ValueError(f"unknown baseline reason {reason!r}")
    goal = get_goal(db, client_id)
    if goal is None:
        return None
    result = project(db, client_id, goal)
    db.query(models.GoalBaseline).filter_by(client_id=client_id, is_current=True).update(
        {"is_current": False}, synchronize_session="fetch",
    )
    db.flush()
    row = models.GoalBaseline(
        client_id=client_id, scenario_id=goal.id, scenario_name=goal.name, reason=reason,
        anchor_date=today or date.today(), is_current=True,
        assumptions={field: result[field] for field in ("annual_return", "inflation", "horizon_years", "monthly_savings")},
        projection=[{"offset": index, "year": row["year"], "p10": row["p10"], "p50": row["p50"], "p90": row["p90"]}
                    for index, row in enumerate(result["projection"])],
        events=[{"name": event["name"], "direction": event["direction"], "target_amount": event["target_amount"],
                 "date": event["resolved_date"].isoformat() if event["resolved_date"] else None}
                for event in result["events"]],
    )
    db.add(row)
    db.flush()
    return row


def capture_now(db: Session, client_id: int, reason: str = "manual") -> models.GoalBaseline | None:
    try:
        row = capture(db, client_id, reason)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return row


def _band(projection: list[dict], anchor: date, day: date) -> dict:
    """Linear interpolation of the yearly band at a day after the anchor."""
    years = max(0.0, (day - anchor).days / 365.25)
    last = len(projection) - 1
    index = min(int(years), last)
    upper = min(index + 1, last)
    fraction = 0.0 if upper == index else years - index
    return {key: projection[index][key] + (projection[upper][key] - projection[index][key]) * fraction
            for key in ("p10", "p50", "p90")}


def _month(anchor: date, offset: int) -> tuple[str, date]:
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + offset, 12)
    month += 1
    return f"{year:04d}-{month:02d}", date(year, month, monthrange(year, month)[1])


def comparison(db: Session, client_id: int, *, today: date | None = None) -> dict:
    """The current baseline month by month, with actual net worth up to today."""
    baseline = current(db, client_id)
    if baseline is None:
        return {"baseline": None, "rows": [], "latest": None}
    today = today or date.today()
    anchor = baseline.anchor_date
    elapsed = max(0, (today.year - anchor.year) * 12 + today.month - anchor.month)
    horizon = min(MAX_MONTHS, max(12, elapsed + 6), (len(baseline.projection) - 1) * 12)
    closed = {row.period for row in list_closes(db, client_id)}
    rows = []
    for offset in range(horizon + 1):
        period, month_end = _month(anchor, offset)
        row = {"period": period, "date": month_end.isoformat(), **_band(baseline.projection, anchor, month_end),
               "actual": None, "closed": period in closed}
        if offset <= elapsed:
            # The current month is valued today and compared with the band at today.
            as_of = min(month_end, today)
            row.update(_band(baseline.projection, anchor, as_of))
            row["date"] = as_of.isoformat()
            row["actual"] = get_balance_sheet(db, as_of_date=as_of, client_id=client_id)["net_worth"]
        rows.append(row)
    observed = [row for row in rows if row["actual"] is not None]
    latest = None
    if observed:
        last = observed[-1]
        latest = {"period": last["period"], "date": last["date"], "actual": last["actual"], "p50": last["p50"],
                  "difference": last["actual"] - last["p50"], "below_p10": last["actual"] < last["p10"],
                  "closed": last["closed"]}
    return {"baseline": _describe(baseline), "rows": rows, "latest": latest}
