from __future__ import annotations

import re
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from .. import models
from .accounting_service import (
    get_balance_sheet,
    get_or_create_account,
    get_profit_loss,
    get_variance_analysis,
    process_transaction,
)
from .goal_service import get_life_events_with_progress

ANOMALY_THRESHOLD_PCT = 150
HIGH_SEVERITY_PCT = 200


def _slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _next_period(period: str) -> str:
    year, month = [int(part) for part in period.split("-")]
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


def _action_key(period: str, proposal_id: str) -> str:
    return f"monthly_report:{period}:{proposal_id}"


def _attach_action_status(
    db: Session,
    client_id: int,
    period: str,
    proposals: list[dict],
) -> list[dict]:
    if not proposals:
        return proposals

    ids = [proposal["id"] for proposal in proposals]
    actions = db.query(models.MonthlyAction).filter(
        models.MonthlyAction.client_id == client_id,
        models.MonthlyAction.source_period == period,
        models.MonthlyAction.proposal_id.in_(ids),
    ).all()
    by_proposal_id = {action.proposal_id: action for action in actions}

    for proposal in proposals:
        action = by_proposal_id.get(proposal["id"])
        proposal["action_status"] = action.status if action else "pending"
        proposal["applied"] = bool(action and action.status == "applied")
        proposal["monthly_action_id"] = action.id if action else None
    return proposals


def generate_monthly_report(db: Session, client_id: int, year: int, month: int) -> dict:
    if month == 12:
        next_month_start = date(year + 1, 1, 1)
    else:
        next_month_start = date(year, month + 1, 1)

    prev_day = date(year, month, 1) - relativedelta(days=1)
    current_period_end = next_month_start - relativedelta(days=1)
    previous_period_end = prev_day

    bs_current = get_balance_sheet(db, next_month_start, client_id)
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

    current_events = get_life_events_with_progress(
        db,
        client_id,
        reference_date=current_period_end,
    )
    previous_events = get_life_events_with_progress(
        db,
        client_id,
        reference_date=previous_period_end,
    )
    previous_by_id = {event["id"]: event for event in previous_events}

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
                "status": event["status"],
            }
        )

    period = f"{year}-{month:02d}"
    action_proposals = []
    surplus = pl["net_profit_loss"]
    if surplus > 0 and current_events:
        worst_event = min(current_events, key=lambda e: e["progress_percentage"])
        amount = round(surplus, 0)
        proposal_id = f"{period}_allocate_to_goal_{worst_event['id']}_{int(amount)}"
        action_proposals.append(
            {
                "id": proposal_id,
                "kind": "allocate_to_goal",
                "type": "invest_surplus",
                "description": (
                    f"Monthly surplus JPY {surplus:,.0f} can be allocated to "
                    f"{worst_event['name']} to improve success probability."
                ),
                "amount": amount,
                "target_id": worst_event["id"],
                "target_life_event_id": worst_event["id"],
                "auto_executable": True,
            }
        )

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
                "target_life_event_id": None,
                "auto_executable": False,
                "navigation_target": "strategy",
            }
        )
    action_proposals = _attach_action_status(db, client_id, period, action_proposals)

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


def _apply_allocate_to_goal(
    db: Session,
    client_id: int,
    period: str,
    proposal: dict,
) -> dict:
    target_id = proposal.get("target_id") or proposal.get("target_life_event_id")
    amount = float(proposal.get("amount") or 0.0)
    if amount <= 0:
        raise ValueError("Proposal amount must be positive")

    goal = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == target_id,
        models.LifeEvent.client_id == client_id,
    ).first()
    if not goal:
        raise LookupError("Target goal not found")

    cash_account = get_or_create_account(db, "cash", client_id, "asset")
    savings_account = get_or_create_account(db, "savings", client_id, "asset")

    transaction = models.Transaction(
        client_id=client_id,
        date=date.today(),
        description=f"Monthly action allocation {period}: {goal.name}",
        amount=amount,
        type="Transfer",
        from_account_id=cash_account.id,
        to_account_id=savings_account.id,
        currency="JPY",
        category="monthly_action",
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    process_transaction(db, transaction)
    db.refresh(savings_account)

    existing = db.query(models.GoalAllocation).filter(
        models.GoalAllocation.life_event_id == goal.id,
        models.GoalAllocation.account_id == savings_account.id,
    ).first()
    other_allocations = db.query(models.GoalAllocation).join(models.LifeEvent).filter(
        models.GoalAllocation.account_id == savings_account.id,
        models.LifeEvent.client_id == client_id,
        models.GoalAllocation.id != (existing.id if existing else -1),
    ).all()
    max_allowed = max(0.0, 100.0 - sum(a.allocation_percentage for a in other_allocations))
    balance = max(abs(savings_account.balance or 0.0), amount)
    proposed_pct = min(100.0, amount / balance * 100.0)

    allocation = existing
    if existing:
        existing.allocation_percentage = min(
            max_allowed,
            (existing.allocation_percentage or 0.0) + proposed_pct,
        )
    elif max_allowed > 0:
        allocation = models.GoalAllocation(
            life_event_id=goal.id,
            account_id=savings_account.id,
            allocation_percentage=min(max_allowed, proposed_pct),
        )
        db.add(allocation)
    db.commit()
    if allocation:
        db.refresh(allocation)

    return {
        "transaction_id": transaction.id,
        "goal_id": goal.id,
        "account_id": savings_account.id,
        "allocation_id": allocation.id if allocation else None,
        "allocation_percentage": round(allocation.allocation_percentage, 2) if allocation else 0.0,
    }


def apply_monthly_report_proposal(
    db: Session,
    client_id: int,
    period: str,
    proposal_id: str,
) -> dict:
    year, month = [int(part) for part in period.split("-")]
    report = generate_monthly_report(db, client_id, year, month)
    proposal = next(
        (item for item in report["action_proposals"] if item.get("id") == proposal_id),
        None,
    )
    if not proposal:
        raise LookupError("Proposal not found")
    if not proposal.get("auto_executable"):
        raise ValueError("Proposal is not auto executable")

    idempotency_key = _action_key(period, proposal_id)
    action = db.query(models.MonthlyAction).filter(
        models.MonthlyAction.client_id == client_id,
        models.MonthlyAction.idempotency_key == idempotency_key,
    ).first()
    if action and action.status == "applied":
        return {
            "status": "already_applied",
            "action": _monthly_action_to_dict(action),
        }

    if not action:
        action = models.MonthlyAction(
            client_id=client_id,
            source_period=period,
            target_period=_next_period(period),
            proposal_id=proposal_id,
            kind=proposal["kind"],
            description=proposal["description"],
            amount=proposal.get("amount"),
            target_id=proposal.get("target_id"),
            payload=proposal,
            status="pending",
            idempotency_key=idempotency_key,
        )
        db.add(action)
        db.commit()
        db.refresh(action)

    try:
        if proposal["kind"] == "allocate_to_goal":
            result = _apply_allocate_to_goal(db, client_id, period, proposal)
        else:
            raise ValueError(f"Unsupported proposal kind: {proposal['kind']}")

        action.status = "applied"
        action.applied_at = datetime.utcnow()
        action.result = result
        db.commit()
        db.refresh(action)
        return {
            "status": "applied",
            "action": _monthly_action_to_dict(action),
        }
    except Exception as exc:
        action.status = "failed"
        action.result = {"error": str(exc)}
        db.commit()
        raise


def _monthly_action_to_dict(action: models.MonthlyAction) -> dict:
    return {
        "id": action.id,
        "source_period": action.source_period,
        "target_period": action.target_period,
        "proposal_id": action.proposal_id,
        "kind": action.kind,
        "description": action.description,
        "amount": action.amount,
        "target_id": action.target_id,
        "payload": action.payload or {},
        "result": action.result or {},
        "status": action.status,
        "applied_at": action.applied_at.isoformat() if action.applied_at else None,
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }
