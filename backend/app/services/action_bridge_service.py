from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from .. import models


ACTION_KINDS = {
    "set_budget",
    "add_recurring",
    "pause_recurring",
    "boost_allocation",
    "change_capsule_contribution",
}


def next_period(period: str) -> str:
    year, month = [int(part) for part in period.split("-")]
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


def action_to_dict(action: models.MonthlyAction) -> dict:
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


def list_actions(
    db: Session,
    client_id: int,
    source_period: str | None = None,
    target_period: str | None = None,
) -> list[dict]:
    query = db.query(models.MonthlyAction).filter(models.MonthlyAction.client_id == client_id)
    if source_period:
        query = query.filter(models.MonthlyAction.source_period == source_period)
    if target_period:
        query = query.filter(models.MonthlyAction.target_period == target_period)
    return [
        action_to_dict(action)
        for action in query.order_by(models.MonthlyAction.created_at.desc(), models.MonthlyAction.id.desc()).all()
    ]


def create_action(
    db: Session,
    client_id: int,
    source_period: str,
    kind: str,
    payload: dict,
    target_period: str | None = None,
    description: str = "",
) -> dict:
    if kind not in ACTION_KINDS:
        raise ValueError(f"Unsupported action kind: {kind}")
    action = models.MonthlyAction(
        client_id=client_id,
        source_period=source_period,
        target_period=target_period or next_period(source_period),
        proposal_id=f"review_{kind}_{uuid4().hex[:10]}",
        kind=kind,
        description=description or kind.replace("_", " "),
        amount=payload.get("amount") or payload.get("monthly_contribution"),
        target_id=payload.get("account_id") or payload.get("recurring_id") or payload.get("life_event_id") or payload.get("capsule_id"),
        payload=payload,
        result={},
        status="pending",
        idempotency_key=f"review:{client_id}:{source_period}:{uuid4().hex}",
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action_to_dict(action)


def _require_account(db: Session, client_id: int, account_id: int) -> models.Account:
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
    ).first()
    if not account:
        raise ValueError("Account not found")
    return account


def _apply_set_budget(db: Session, action: models.MonthlyAction) -> dict:
    payload = action.payload or {}
    account_id = int(payload["account_id"])
    amount = float(payload["amount"])
    target_period = action.target_period or next_period(action.source_period)
    account = _require_account(db, action.client_id, account_id)
    plan_line = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == action.client_id,
        models.MonthlyPlanLine.account_id == account_id,
        models.MonthlyPlanLine.target_period == target_period,
        models.MonthlyPlanLine.line_type == "expense",
    ).first()
    if plan_line:
        plan_line.amount = amount
        plan_line.name = account.name
        plan_line.is_active = True
    else:
        plan_line = models.MonthlyPlanLine(
            client_id=action.client_id,
            target_period=target_period,
            line_type="expense",
            target_type="account",
            account_id=account_id,
            name=account.name,
            amount=amount,
        )
        db.add(plan_line)
    db.flush()
    return {"plan_line_id": plan_line.id, "target_period": target_period}


def _apply_add_recurring(db: Session, action: models.MonthlyAction) -> dict:
    payload = action.payload or {}
    recurring = models.RecurringTransaction(
        client_id=action.client_id,
        name=payload["name"],
        amount=float(payload["amount"]),
        type=payload.get("type", "Expense"),
        from_account_id=payload.get("from_account_id"),
        to_account_id=payload.get("to_account_id"),
        frequency=payload.get("frequency", "Monthly"),
        day_of_month=int(payload.get("day_of_month") or 1),
        month_of_year=payload.get("month_of_year"),
        is_active=True,
    )
    db.add(recurring)
    db.flush()
    return {"recurring_id": recurring.id}


def _apply_pause_recurring(db: Session, action: models.MonthlyAction) -> dict:
    recurring_id = int((action.payload or {})["recurring_id"])
    recurring = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.client_id == action.client_id,
    ).first()
    if not recurring:
        raise ValueError("Recurring transaction not found")
    recurring.is_active = False
    return {"recurring_id": recurring.id, "is_active": False}


def _apply_boost_allocation(db: Session, action: models.MonthlyAction) -> dict:
    payload = action.payload or {}
    life_event_id = int(payload["life_event_id"])
    account_id = int(payload["account_id"])
    delta = float(payload.get("delta_percent") or payload.get("percent") or 0)
    goal = db.query(models.LifeEvent).filter(
        models.LifeEvent.id == life_event_id,
        models.LifeEvent.client_id == action.client_id,
    ).first()
    if not goal:
        raise ValueError("Life event not found")
    _require_account(db, action.client_id, account_id)
    allocation = db.query(models.GoalAllocation).filter(
        models.GoalAllocation.life_event_id == life_event_id,
        models.GoalAllocation.account_id == account_id,
    ).first()
    if allocation:
        allocation.allocation_percentage = min(100.0, allocation.allocation_percentage + delta)
    else:
        allocation = models.GoalAllocation(
            life_event_id=life_event_id,
            account_id=account_id,
            allocation_percentage=min(100.0, max(0.1, delta)),
        )
        db.add(allocation)
    return {"allocation_id": allocation.id, "allocation_percentage": allocation.allocation_percentage}


def _apply_change_capsule_contribution(db: Session, action: models.MonthlyAction) -> dict:
    payload = action.payload or {}
    capsule = db.query(models.Capsule).filter(
        models.Capsule.id == int(payload["capsule_id"]),
        models.Capsule.client_id == action.client_id,
    ).first()
    if not capsule:
        raise ValueError("Capsule not found")
    capsule.monthly_contribution = float(payload["monthly_contribution"])
    return {"capsule_id": capsule.id, "monthly_contribution": capsule.monthly_contribution}


DISPATCH = {
    "set_budget": _apply_set_budget,
    "add_recurring": _apply_add_recurring,
    "pause_recurring": _apply_pause_recurring,
    "boost_allocation": _apply_boost_allocation,
    "change_capsule_contribution": _apply_change_capsule_contribution,
}


def apply_action(db: Session, client_id: int, action_id: int) -> dict:
    action = db.query(models.MonthlyAction).filter(
        models.MonthlyAction.id == action_id,
        models.MonthlyAction.client_id == client_id,
    ).first()
    if not action:
        raise LookupError("Action not found")
    if action.status == "applied":
        return action_to_dict(action)
    if action.kind not in DISPATCH:
        raise ValueError(f"Unsupported action kind: {action.kind}")

    try:
        result = DISPATCH[action.kind](db, action)
        action.status = "applied"
        action.applied_at = datetime.utcnow()
        action.result = result
        db.commit()
        db.refresh(action)
        return action_to_dict(action)
    except Exception as exc:
        action.status = "failed"
        action.result = {"error": str(exc)}
        db.commit()
        raise


def skip_action(db: Session, client_id: int, action_id: int) -> dict:
    action = db.query(models.MonthlyAction).filter(
        models.MonthlyAction.id == action_id,
        models.MonthlyAction.client_id == client_id,
    ).first()
    if not action:
        raise LookupError("Action not found")
    action.status = "skipped"
    db.commit()
    db.refresh(action)
    return action_to_dict(action)


def process_due_actions(db: Session, client_id: int, today: date | None = None) -> list[dict]:
    current_period = (today or date.today()).strftime("%Y-%m")
    actions = db.query(models.MonthlyAction).filter(
        models.MonthlyAction.client_id == client_id,
        models.MonthlyAction.status.in_(["pending", "failed"]),
        models.MonthlyAction.target_period <= current_period,
    ).order_by(models.MonthlyAction.target_period, models.MonthlyAction.id).all()
    processed = []
    for action in actions:
        try:
            processed.append(apply_action(db, client_id, action.id))
        except Exception:
            db.rollback()
            db.refresh(action)
            processed.append(action_to_dict(action))
    return processed
