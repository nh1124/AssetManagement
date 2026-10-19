from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from ..services.money_storage import to_minor, money_client_currency

from .. import models
from ..domain.errors import NotFound, Refused
from ..services import monthly_action_store
from ..services.budget_lines import assign_plan_line_identity
from ..services.budget_plan_store import create_plan_line, find_expense_plan_line, resolve_budget_plan_id
from ..services.capsule_service import (
    capsule_balance,
    create_capsule_for_goal,
    get_capsule,
    claimed_minor,
    account_claimed_minor,
)
from ..services.goal_service import get_life_event
from ..services.ledger_service import get_account, create_transaction
from ..domain.journal import Leg
from ..domain.money import Money
from ..services.ledger_valuation import calculate_account_valued_balance
from ..services.registry_service import get_entry, create_entry, update_entry



ACTION_KINDS = {
    "set_budget",
    "add_auto_transaction",
    "stop_auto_transaction",
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


def _action_fields(
    source_period: str,
    kind: str,
    payload: dict,
    target_period: str | None = None,
    description: str = "",
) -> dict:
    if kind not in ACTION_KINDS:
        raise ValueError(f"Unsupported action kind: {kind}")
    return dict(
        source_period=source_period,
        target_period=target_period or next_period(source_period),
        kind=kind,
        description=description or kind.replace("_", " "),
        amount=payload.get("amount") or payload.get("monthly_contribution"),
        target_id=payload.get("account_id") or payload.get("registry_entry_id") or payload.get("life_event_id") or payload.get("capsule_id"),
        payload=payload,
    )


def create_action(
    db: Session,
    client_id: int,
    source_period: str,
    kind: str,
    payload: dict,
    target_period: str | None = None,
    description: str = "",
) -> dict:
    fields = _action_fields(source_period, kind, payload, target_period, description)
    fields.update(
        proposal_id=f"review_{kind}_{uuid4().hex[:10]}",
        result={},
        status="pending",
        idempotency_key=f"review:{client_id}:{source_period}:{uuid4().hex}",
    )
    action = monthly_action_store.create(db, client_id, fields, commit=False)
    db.commit()
    db.refresh(action)
    return action_to_dict(action)


def _pending_action(db: Session, client_id: int, action_id: int) -> models.MonthlyAction:
    action = monthly_action_store.get(db, client_id, action_id, for_update=True)
    if action is None:
        raise NotFound("行動が見つかりません。")
    # Applied decisions have already changed other resources; only pending records may be rewritten.
    if action.status != "pending":
        state = {"applied": "実行済み", "skipped": "見送り", "failed": "失敗"}.get(action.status, action.status)
        raise Refused(f"現在の状態は「{state}」のため、変更・削除できません。", status_code=422)
    return action


def update_action(
    db: Session,
    client_id: int,
    action_id: int,
    source_period: str,
    kind: str,
    payload: dict,
    target_period: str | None = None,
    description: str = "",
) -> dict:
    action = _pending_action(db, client_id, action_id)
    fields = _action_fields(source_period, kind, payload, target_period, description)
    monthly_action_store.update(db, client_id, action, fields)
    db.commit()
    db.refresh(action)
    return action_to_dict(action)


def delete_action(db: Session, client_id: int, action_id: int) -> dict:
    action = _pending_action(db, client_id, action_id)
    monthly_action_store.delete(db, action)
    db.commit()
    return {"status": "ok"}


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


def _apply_add_automatic(db: Session, action: models.MonthlyAction) -> dict:
    from ..schemas import RegistryEntryCreate
    payload = RegistryEntryCreate(**(action.payload or {})).model_dump()
    entry = create_entry(db, action.client_id, payload)
    return {"registry_entry_id": entry.id}


def _apply_stop_automatic(db: Session, action: models.MonthlyAction) -> dict:
    entry_id = int((action.payload or {})["registry_entry_id"])
    entry = update_entry(db, action.client_id, entry_id, {"is_active": False})
    if entry is None:
        raise ValueError("Automatic transaction not found")
    return {"registry_entry_id": entry.id, "is_active": False}


def _apply_boost_allocation(db: Session, action: models.MonthlyAction) -> dict:
    """Earmark a larger share of one account for a goal.

    Apply delta_percent to the account balance, then post a balanced entry
    at the same account. The attributed leg changes the capsule claim; its
    unattributed counterparty preserves the account balance.
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
    currency = money_client_currency(db, action.client_id)
    claimed = Money(account_claimed_minor(db, action.client_id, account_id).get(currency, 0), currency).to_float()
    headroom = max(0.0, balance - float(claimed))
    applied = min(requested, headroom) if requested > 0 else requested

    current_claim = claimed_minor(db, action.client_id, capsule.id, account_id).get(currency, 0)
    delta = Money.from_major(str(applied), currency).minor
    delta = max(delta, -max(0, current_claim))
    applied = Money(delta, currency).to_float()
    if delta:
        create_transaction(db, client_id=action.client_id, date=date.today(),
            description=f"boost_allocation {delta_percent:+g}% ({action.source_period})",
            amount_minor=abs(delta), currency=currency,
            legs=[Leg(account_id, debit=max(0, delta), credit=max(0, -delta), capsule_id=capsule.id),
                  Leg(account_id, debit=max(0, -delta), credit=max(0, delta))])
    db.flush()
    return {
        "capsule_id": capsule.id,
        "account_id": account_id,
        "delta_percent": delta_percent,
        "requested_amount": round(requested, 2),
        "applied_amount": round(applied, 2),
        "clamped": applied < requested,
        "claimed_amount": Money(claimed_minor(db, action.client_id, capsule.id, account_id).get(currency, 0), currency).to_float(),
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
    "add_auto_transaction": _apply_add_automatic,
    "stop_auto_transaction": _apply_stop_automatic,
    "boost_allocation": _apply_boost_allocation,
    "change_capsule_contribution": _apply_change_capsule_contribution,
}


def apply_action(db: Session, client_id: int, action_id: int) -> dict:
    action = monthly_action_store.get(db, client_id, action_id, for_update=True)
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
    action = monthly_action_store.get(db, client_id, action_id, for_update=True)
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
