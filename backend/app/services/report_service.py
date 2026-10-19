from __future__ import annotations

import re
from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from .reporting_service import (
    get_balance_sheet,
    get_profit_loss,
    get_profit_loss_for_range,
    get_variance_analysis,
    get_variance_analysis_for_range,
)
from .goal_earmark_service import events_with_progress

ANOMALY_THRESHOLD_PCT = 150
HIGH_SEVERITY_PCT = 200


def _slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _period_key(start_date: date, end_date: date) -> str:
    return f"{start_date.isoformat()}..{end_date.isoformat()}"


def generate_monthly_report(db: Session, client_id: int, year: int, month: int) -> dict:
    if month == 12:
        next_month_start = date(year + 1, 1, 1)
    else:
        next_month_start = date(year, month + 1, 1)

    prev_day = date(year, month, 1) - relativedelta(days=1)
    current_period_end = next_month_start - relativedelta(days=1)
    previous_period_end = prev_day

    bs_current = get_balance_sheet(db, current_period_end, client_id)
    bs_prev = get_balance_sheet(db, prev_day, client_id)
    net_worth_change = bs_current["net_worth"] - bs_prev["net_worth"]
    net_worth_change_pct = (net_worth_change / bs_prev["net_worth"] * 100) if bs_prev["net_worth"] else 0

    pl = get_profit_loss(db, year, month, client_id)
    savings_rate = (pl["net_profit_loss"] / pl["total_income"] * 100) if pl["total_income"] else 0

    variance = get_variance_analysis(db, year, month, client_id)
    anomalies = []
    for item in variance.get("items", []):
        if item["budget"] > 0 and item["actual"] > 0:
            pct = item["actual"] / item["budget"] * 100
            if pct >= ANOMALY_THRESHOLD_PCT:
                anomalies.append(
                    {
                        "category": item["category"],
                        "budget": item["budget"],
                        "actual": item["actual"],
                        "overage_pct": round(pct, 1),
                        "severity": "high" if pct >= HIGH_SEVERITY_PCT else "medium",
                    }
                )

    current_events = events_with_progress(db, client_id, reference_date=current_period_end)
    previous_events = events_with_progress(db, client_id, reference_date=previous_period_end)
    current_events = [event for event in current_events if event.get("direction", "expense") == "expense"]
    previous_by_id = {event["id"]: event for event in previous_events if event.get("direction", "expense") == "expense"}

    goal_progress = []
    for event in current_events:
        previous_probability = previous_by_id.get(event["id"], {}).get(
            "progress_percentage",
            event["progress_percentage"],
        )
        current_probability = event["progress_percentage"]
        delta = round(current_probability - previous_probability, 1)

        goal_progress.append(
            {
                "id": event["id"],
                "name": event["name"],
                "probability_current": round(current_probability, 1),
                "probability_last_month": round(previous_probability, 1),
                "delta": delta,
            }
        )

    period = f"{year}-{month:02d}"
    action_proposals = []
    for anomaly in anomalies:
        overage = anomaly["actual"] - anomaly["budget"]
        proposal_id = f"{period}_review_budget_{_slug(anomaly['category'])}"
        action_proposals.append(
            {
                "id": proposal_id,
                "kind": "review_budget",
                "type": "reduce_spending",
                "description": (
                    f"{anomaly['category']} spending is {anomaly['overage_pct']:.0f}% of budget. "
                    f"Reduce by JPY {overage:,.0f} next month."
                ),
                "amount": round(overage, 0),
                "target_id": None,
            }
        )

    return {
        "period": period,
        "summary": {
            "net_worth": bs_current["net_worth"],
            "net_worth_change": round(net_worth_change, 0),
            "net_worth_change_pct": round(net_worth_change_pct, 1),
            "monthly_pl": pl["net_profit_loss"],
            "savings_rate": round(savings_rate, 1),
        },
        "goal_progress": goal_progress,
        "anomalies": anomalies,
        "action_proposals": action_proposals,
    }


def generate_period_report(db: Session, client_id: int, start_date: date, end_date: date) -> dict:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")

    previous_period_end = start_date - relativedelta(days=1)
    period = _period_key(start_date, end_date)

    bs_current = get_balance_sheet(db, end_date, client_id)
    bs_prev = get_balance_sheet(db, previous_period_end, client_id)
    net_worth_change = bs_current["net_worth"] - bs_prev["net_worth"]
    net_worth_change_pct = (net_worth_change / bs_prev["net_worth"] * 100) if bs_prev["net_worth"] else 0

    pl = get_profit_loss_for_range(db, start_date, end_date, client_id)
    period_pl = pl["net_profit_loss"]
    savings_rate = (period_pl / pl["total_income"] * 100) if pl["total_income"] else 0

    variance = get_variance_analysis_for_range(db, start_date, end_date, client_id)
    anomalies = []
    for item in variance.get("items", []):
        if item["budget"] > 0 and item["actual"] > 0:
            pct = item["actual"] / item["budget"] * 100
            if pct >= ANOMALY_THRESHOLD_PCT:
                anomalies.append(
                    {
                        "category": item["category"],
                        "budget": item["budget"],
                        "actual": item["actual"],
                        "overage_pct": round(pct, 1),
                        "severity": "high" if pct >= HIGH_SEVERITY_PCT else "medium",
                    }
                )

    current_events = events_with_progress(db, client_id, reference_date=end_date)
    previous_events = events_with_progress(db, client_id, reference_date=previous_period_end)
    current_events = [event for event in current_events if event.get("direction", "expense") == "expense"]
    previous_by_id = {event["id"]: event for event in previous_events if event.get("direction", "expense") == "expense"}

    goal_progress = []
    for event in current_events:
        previous_probability = previous_by_id.get(event["id"], {}).get(
            "progress_percentage",
            event["progress_percentage"],
        )
        current_probability = event["progress_percentage"]
        goal_progress.append(
            {
                "id": event["id"],
                "name": event["name"],
                "probability_current": round(current_probability, 1),
                "probability_previous_period": round(previous_probability, 1),
                "delta": round(current_probability - previous_probability, 1),
            }
        )

    action_proposals = []
    for anomaly in anomalies:
        overage = anomaly["actual"] - anomaly["budget"]
        proposal_id = f"{_slug(period)}_review_budget_{_slug(anomaly['category'])}"
        action_proposals.append(
            {
                "id": proposal_id,
                "kind": "review_budget",
                "type": "reduce_spending",
                "description": (
                    f"{anomaly['category']} spending is {anomaly['overage_pct']:.0f}% of budget. "
                    f"Review budget allocation for the next planning period."
                ),
                "amount": round(overage, 0),
                "target_id": None,
            }
        )

    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "summary": {
            "net_worth": bs_current["net_worth"],
            "net_worth_change": round(net_worth_change, 0),
            "net_worth_change_pct": round(net_worth_change_pct, 1),
            "monthly_pl": period_pl,
            "period_pl": period_pl,
            "savings_rate": round(savings_rate, 1),
        },
        "goal_progress": goal_progress,
        "anomalies": anomalies,
        "action_proposals": action_proposals,
    }

