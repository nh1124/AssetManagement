"""Reading and writing budget plans and their monthly plan lines.

This is the persistence half of planning: which plan is the default, which
plan a request means, and the create/update path for MonthlyPlanLine rows
including the duplicate check that keeps one identity to one active line.
Nothing here computes a summary, so it sits below everything that does.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models
from .budget_lines import (
    _line_source_id,
    _line_source_kind,
    assign_plan_line_identity,
    line_identity_key,
    newest_line_key,
)
from .registry_service import registry_target_account_id


def get_or_create_default_plan(db: Session, client_id: int) -> models.BudgetPlan:
    defaults = (
        db.query(models.BudgetPlan)
        .filter_by(client_id=client_id, is_default=True)
        .order_by(models.BudgetPlan.sort_order, models.BudgetPlan.id)
        .all()
    )
    plan = defaults[0] if defaults else None
    if not plan:
        plan = db.query(models.BudgetPlan).filter_by(client_id=client_id, name="Baseline").first()
        if plan:
            plan.is_default = True
            plan.sort_order = min(plan.sort_order or 0, 0)
        else:
            plan = models.BudgetPlan(client_id=client_id, name="Baseline", is_default=True, sort_order=0)
            db.add(plan)
        db.commit()
        db.refresh(plan)
    elif len(defaults) > 1:
        for extra in defaults[1:]:
            extra.is_default = False
        db.add(plan)
        db.commit()
        db.refresh(plan)
    changed = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id.is_(None),
        models.MonthlyPlanLine.is_active.is_(True),
    ).update({"plan_id": plan.id})
    if changed:
        db.commit()
        db.refresh(plan)
    return plan


def replace_plan_lines_from_plan(
    db: Session,
    client_id: int,
    target_plan_id: int,
    source_plan_id: int,
) -> int:
    if target_plan_id == source_plan_id:
        return 0

    target_plan = db.query(models.BudgetPlan).filter_by(id=target_plan_id, client_id=client_id).first()
    if not target_plan:
        raise ValueError("Target budget plan not found")
    source_plan = db.query(models.BudgetPlan).filter_by(id=source_plan_id, client_id=client_id).first()
    if not source_plan:
        raise ValueError("Source budget plan not found")

    source_lines = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.plan_id == source_plan_id,
            models.MonthlyPlanLine.is_active.is_(True),
        )
        .all()
    )

    (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.plan_id == target_plan_id,
        )
        .update({"is_active": False}, synchronize_session=False)
    )

    for src in source_lines:
        new_line = models.MonthlyPlanLine(
            client_id=client_id,
            plan_id=target_plan_id,
            target_period=src.target_period,
            line_type=src.line_type,
            target_type=src.target_type,
            target_id=src.target_id,
            account_id=src.account_id,
            source_account_id=src.source_account_id,
            name=src.name,
            amount=src.amount,
            source=src.source,
            source_kind=src.source_kind,
            source_id=src.source_id,
            manual_override=src.manual_override,
            cash_treatment=src.cash_treatment,
            recurring_transaction_id=src.recurring_transaction_id,
            is_active=True,
        )
        assign_plan_line_identity(new_line)
        db.add(new_line)
    return len(source_lines)


def set_default_budget_plan(db: Session, client_id: int, plan_id: int) -> models.BudgetPlan:
    plan = db.query(models.BudgetPlan).filter_by(id=plan_id, client_id=client_id).first()
    if not plan:
        raise ValueError("Budget plan not found")
    for item in db.query(models.BudgetPlan).filter_by(client_id=client_id).all():
        item.is_default = item.id == plan.id
    db.commit()
    db.refresh(plan)
    return plan


def resolve_budget_plan_id(db: Session, client_id: int, plan_id: int | None = None) -> int:
    if plan_id is None:
        return get_or_create_default_plan(db, client_id).id
    exists = db.query(models.BudgetPlan.id).filter(
        models.BudgetPlan.id == plan_id,
        models.BudgetPlan.client_id == client_id,
    ).first()
    if not exists:
        raise ValueError("Budget plan not found")
    return plan_id


def _deduplicate_active_plan_models(
    db: Session,
    plan_models: list[models.MonthlyPlanLine],
    *,
    repair: bool = False,
) -> list[models.MonthlyPlanLine]:
    grouped: dict[tuple, list[models.MonthlyPlanLine]] = {}
    for line in plan_models:
        grouped.setdefault(line_identity_key(line), []).append(line)

    deduped: list[models.MonthlyPlanLine] = []
    changed = False
    for lines in grouped.values():
        if len(lines) == 1:
            deduped.append(lines[0])
            continue
        keeper = max(lines, key=newest_line_key)
        deduped.append(keeper)
        for duplicate in lines:
            if duplicate.id != keeper.id:
                if repair:
                    duplicate.is_active = False
                    changed = True

    if repair and changed:
        db.commit()
    return sorted(deduped, key=lambda line: (line.line_type, line.id))


def _active_line_with_identity(
    db: Session,
    client_id: int,
    data: dict,
    exclude_id: int | None = None,
) -> models.MonthlyPlanLine | None:
    key = line_identity_key({**data, "target_period": data.get("target_period")})
    q = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.target_period == data.get("target_period"),
        models.MonthlyPlanLine.line_type == data.get("line_type"),
        models.MonthlyPlanLine.is_active.is_(True),
    )
    plan_id = data.get("plan_id")
    if plan_id is not None:
        q = q.filter(models.MonthlyPlanLine.plan_id == plan_id)
    rows = q.all()
    return next((line for line in rows if line.id != exclude_id and line_identity_key(line) == key), None)


def _active_duplicate_for_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine,
) -> models.MonthlyPlanLine | None:
    return _active_line_with_identity(
        db,
        client_id,
        {
            "plan_id": line.plan_id,
            "target_period": line.target_period,
            "source_kind": _line_source_kind(line),
            "source_id": _line_source_id(line),
            "line_type": line.line_type,
            "target_type": line.target_type,
            "target_id": line.target_id,
            "account_id": line.account_id,
            "source_account_id": line.source_account_id,
            "name": line.name,
            "cash_treatment": line.cash_treatment,
        },
        exclude_id=line.id,
    )


def _payload_data(payload) -> dict:
    return payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)


def _apply_plan_line_data(db: Session, client_id: int, line: models.MonthlyPlanLine, data: dict) -> None:
    for key, value in data.items():
        if key != "id":
            setattr(line, key, value)
    line.source_kind = _line_source_kind(line)
    if line.source_id is None:
        line.source_id = _line_source_id(line)
    if line.source == "manual":
        line.source_kind = "manual"
        line.source_id = None
    # Normalize manual lines: if no account_id is set but the registry has one for
    # this line_type+name, promote target_type to "account" so future matching works.
    if (not line.account_id) and line.target_type in (None, "manual") and line.name and line.line_type:
        registry_entry = db.query(models.RegistryEntry).filter(
            models.RegistryEntry.client_id == client_id,
            models.RegistryEntry.is_active.is_(True),
            models.RegistryEntry.name == line.name,
            models.RegistryEntry.line_type == line.line_type,
        ).first()
        if registry_entry:
            resolved = registry_target_account_id(registry_entry)
            if resolved:
                line.account_id = resolved
                line.target_type = "account"
    if line.target_type == "account" and line.account_id and not line.name:
        account = db.query(models.Account).filter(
            models.Account.id == line.account_id,
            models.Account.client_id == client_id,
        ).first()
        if account:
            line.name = account.name
    if line.target_type == "capsule" and line.target_id:
        capsule = db.query(models.Capsule).filter(
            models.Capsule.id == line.target_id,
            models.Capsule.client_id == client_id,
        ).first()
        if capsule:
            line.name = capsule.name
            line.account_id = capsule.account_id
            capsule.monthly_contribution = line.amount or 0.0
            if line.source in {None, "manual", "capsule"}:
                line.source_kind = "capsule"
                line.source_id = capsule.id
    assign_plan_line_identity(line)


def create_plan_lines(db: Session, client_id: int, payloads: list) -> list[models.MonthlyPlanLine]:
    created: list[models.MonthlyPlanLine] = []
    for payload in payloads:
        data = _payload_data(payload)
        data.pop("id", None)
        data["plan_id"] = resolve_budget_plan_id(db, client_id, data.get("plan_id"))
        if _active_line_with_identity(db, client_id, data):
            raise ValueError("Monthly plan line already exists for this period and target")
        line = models.MonthlyPlanLine(client_id=client_id)
        db.add(line)
        _apply_plan_line_data(db, client_id, line, data)
        duplicate = _active_duplicate_for_line(db, client_id, line)
        if duplicate:
            db.rollback()
            raise ValueError("Monthly plan line already exists for this period and source")
        created.append(line)
    db.commit()
    for line in created:
        db.refresh(line)
    return created


def update_plan_lines(
    db: Session,
    client_id: int,
    payloads: list,
    *,
    commit: bool = True,
) -> list[models.MonthlyPlanLine]:
    saved: list[models.MonthlyPlanLine] = []
    for payload in payloads:
        data = _payload_data(payload)
        line_id = data.pop("id", None)
        if not line_id:
            raise ValueError("Monthly plan line id is required")
        line = db.query(models.MonthlyPlanLine).filter(
            models.MonthlyPlanLine.id == line_id,
            models.MonthlyPlanLine.client_id == client_id,
        ).first()
        if not line:
            raise ValueError("Monthly plan line not found")
        if "plan_id" in data:
            data["plan_id"] = resolve_budget_plan_id(db, client_id, data.get("plan_id"))
        elif line.plan_id is None:
            data["plan_id"] = resolve_budget_plan_id(db, client_id)
        _apply_plan_line_data(db, client_id, line, data)
        duplicate = _active_duplicate_for_line(db, client_id, line)
        if duplicate:
            db.rollback()
            raise ValueError("Monthly plan line already exists for this period and source")
        saved.append(line)
    if commit:
        db.commit()
        for line in saved:
            db.refresh(line)
    else:
        db.flush()
    return saved
