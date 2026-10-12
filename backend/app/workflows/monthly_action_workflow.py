from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from ..services.money_storage import to_minor, money_client_currency

from .. import models
from ..services import monthly_action_store
from ..services.budget_lines import assign_plan_line_identity
from ..services.budget_plan_store import create_plan_line, find_expense_plan_line, resolve_budget_plan_id
from ..services.capsule_service import (
    capsule_balance,
    create_capsule_for_goal,
    get_capsule,
    total_held_amount_for_account,
    upsert_capsule_holding,
)
from ..services.goal_service import get_life_event
from ..services.ledger_service import get_account
from ..services.ledger_valuation import calculate_account_valued_balance
from ..services.registry_service import (
    get_entry,
    get_recurring_transaction,
    sync_recurring_from_registry,
    upsert_registry_from_recurring_payload,
)


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
    return [
        action_to_dict(action)
        for action in monthly_action_store.list_for_client(
            db, client_id, period=source_period, target_period=target_period,
        )
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
    fields = dict(
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
    action = monthly_action_store.create(db, client_id, fields, commit=False)
    db.commit()
    db.refresh(action)
    return action_to_dict(action)


def _require_account(db: Session, client_id: int, account_id: int) -> models.Account:
    account = get_account(db, client_id, account_id)
    if not account:
        raise ValueError("Account not found")
    return account


def _apply_set_budget(db: Session, action: models.MonthlyAction) -> dict:
    payload = action.payload or {}
    account_id = int(payload["account_id"])
    amount = float(payload["amount"])
    plan_id = resolve_budget_plan_id(db, action.client_id, payload.get("plan_id"))
    target_period = action.target_period or next_period(action.source_period)
    account = _require_account(db, action.client_id, account_id)
    plan_line = find_expense_plan_line(db, action.client_id, plan_id, account_id, target_period)
    if plan_line:
        plan_line.amount_minor = to_minor(amount, money_client_currency(db, action.client_id))
        plan_line.name = account.name
        plan_line.is_active = True
        assign_plan_line_identity(plan_line)
    else:
        plan_line = create_plan_line(db, action.client_id, dict(
            plan_id=plan_id,
            target_period=target_period,
            line_type="expense",
            target_type="account",
            account_id=account_id,
            name=account.name,
            amount=amount,
        ), commit=False)
    db.flush()
    return {"plan_line_id": plan_line.id, "target_period": target_period, "plan_id": plan_id}


def _apply_add_recurring(db: Session, action: models.MonthlyAction) -> dict:
    payload = action.payload or {}
    recurring_payload = {
        "name": payload["name"],
        "amount": float(payload["amount"]),
        "currency": payload.get("currency"),
        "from_account_id": payload.get("from_account_id"),
        "to_account_id": payload.get("to_account_id"),
        "frequency": payload.get("frequency", "Monthly"),
        "day_of_month": int(payload.get("day_of_month") or 1),
        "month_of_year": payload.get("month_of_year"),
        "is_active": True,
    }
    recurring = upsert_registry_from_recurring_payload(db, action.client_id, recurring_payload)
    return {"recurring_id": recurring.id}


def _apply_pause_recurring(db: Session, action: models.MonthlyAction) -> dict:
    recurring_id = int((action.payload or {})["recurring_id"])
    recurring = get_recurring_transaction(db, action.client_id, recurring_id)
    if not recurring:
        raise ValueError("Recurring transaction not found")
    entry = get_entry(db, action.client_id, recurring.source_registry_entry_id)
    if entry is None:
        raise ValueError("Recurring transaction not found")
    # A paused definition moves no money, so its entry must stop forecasting it too.
    entry.is_active = False
    sync_recurring_from_registry(db, entry)
    return {"recurring_id": recurring.id, "is_active": False}


def _apply_boost_allocation(db: Session, action: models.MonthlyAction) -> dict:
    """Earmark a larger share of one account for a goal.

    This used to write a GoalAllocation row holding a percentage per
    (goal, account) pair. That table was dropped in v5 and capsule_holdings
    carries the same idea as an amount, so `delta_percent` is now applied
    against the account's balance and accumulated on the goal's capsule.
    """
    payload = action.payload or {}
    life_event_id = int(payload["life_event_id"])
    account_id = int(payload["account_id"])
    delta_percent = float(payload.get("delta_percent") or payload.get("percent") or 0)

    goal = get_life_event(db, action.client_id, life_event_id)
    if not goal:
        raise ValueError("Life event not found")
    account = _require_account(db, action.client_id, account_id)

    capsule = create_capsule_for_goal(db, action.client_id, goal)
    db.flush()

    balance = calculate_account_valued_balance(db, account)
    requested = balance * delta_percent / 100.0

    # An account cannot have more earmarked against it than it holds, counting
    # what other capsules already claim.
    claimed = total_held_amount_for_account(db, account_id)
    headroom = max(0.0, balance - float(claimed))
    applied = min(requested, headroom) if requested > 0 else requested

    holding = upsert_capsule_holding(
        db,
        capsule,
        account_id,
        applied,
        note=f"boost_allocation {delta_percent:+g}% ({action.source_period})",
    )
    db.flush()

    return {
        "capsule_id": capsule.id,
        "account_id": account_id,
        "delta_percent": delta_percent,
        "requested_amount": round(requested, 2),
        "applied_amount": round(applied, 2),
        "clamped": applied < requested,
        "held_amount": round(holding.held_amount, 2),
        "capsule_balance": round(capsule_balance(db, capsule), 2),
    }


def _apply_change_capsule_contribution(db: Session, action: models.MonthlyAction) -> dict:
    payload = action.payload or {}
    capsule = get_capsule(db, action.client_id, int(payload["capsule_id"]))
    if not capsule:
        raise ValueError("Capsule not found")
    capsule.monthly_contribution_minor = to_minor(payload["monthly_contribution"], money_client_currency(db, action.client_id))
    return {"capsule_id": capsule.id, "monthly_contribution": capsule.monthly_contribution}


DISPATCH = {
    "set_budget": _apply_set_budget,
    "add_recurring": _apply_add_recurring,
    "pause_recurring": _apply_pause_recurring,
    "boost_allocation": _apply_boost_allocation,
    "change_capsule_contribution": _apply_change_capsule_contribution,
}


def apply_action(db: Session, client_id: int, action_id: int) -> dict:
    action = monthly_action_store.get(db, client_id, action_id)
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
        # Deliberately match ai_change_request_workflow.apply_change_request so
        # recording a failure cannot commit partial feature writes.
        db.rollback()
        failed_action = monthly_action_store.get(db, client_id, action_id)
        if failed_action is not None:
            failed_action.status = "failed"
            failed_action.result = {"error": str(exc)}
            db.commit()
        raise


def skip_action(db: Session, client_id: int, action_id: int) -> dict:
    action = monthly_action_store.get(db, client_id, action_id)
    if not action:
        raise LookupError("Action not found")
    action.status = "skipped"
    db.commit()
    db.refresh(action)
    return action_to_dict(action)


def process_due_actions(db: Session, client_id: int, today: date | None = None) -> list[dict]:
    actions = monthly_action_store.list_due(db, client_id, today or date.today())
    processed = []
    for action in actions:
        try:
            processed.append(apply_action(db, client_id, action.id))
        except Exception:
            db.rollback()
            db.refresh(action)
            processed.append(action_to_dict(action))
    return processed
