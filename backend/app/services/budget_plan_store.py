"""Reading and writing budget plans and their monthly plan lines.

This is the persistence half of planning: which plan is the default, which
plan a request means, and the create/update path for MonthlyPlanLine rows
including the duplicate check that keeps one identity to one active line.
Nothing here computes a summary, so it sits below everything that does.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from typing import Sequence

from .money_storage import minor_fields, money_client_currency

from .. import models
from ..domain.errors import Invalid
from .budget_lines import (
    _line_source_kind,
    assign_plan_line_identity,
    line_identity_key,
    newest_line_key,
)
from .registry_service import registry_target_account_id


def get_plan_line(db: Session, client_id: int, line_id: int) -> models.MonthlyPlanLine | None:
    return db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.id == line_id,
        models.MonthlyPlanLine.client_id == client_id,
    ).first()


def find_expense_plan_line(
    db: Session, client_id: int, plan_id: int, account_id: int, target_period: str,
) -> models.MonthlyPlanLine | None:
    return db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id == plan_id,
        models.MonthlyPlanLine.account_id == account_id,
        models.MonthlyPlanLine.target_period == target_period,
        models.MonthlyPlanLine.line_type == "expense",
    ).first()


def create_plan_line(
    db: Session, client_id: int, fields: dict, *, commit: bool = False,
) -> models.MonthlyPlanLine:
    # Review actions already resolve their target; batch normalization and
    # duplicate validation would change their existing write behavior.
    line = models.MonthlyPlanLine(**minor_fields(fields, money_client_currency(db, client_id), 'amount'), client_id=client_id)
    db.add(line)
    assign_plan_line_identity(line)
    if commit:
        db.commit()
        db.refresh(line)
    else:
        db.flush()
    return line


def get_plan(db: Session, client_id: int, plan_id: int) -> models.BudgetPlan | None:
    return db.query(models.BudgetPlan).filter(
        models.BudgetPlan.client_id == client_id,
        models.BudgetPlan.id == plan_id,
    ).first()


def list_plans(db: Session, client_id: int) -> list[models.BudgetPlan]:
    plans = (
        db.query(models.BudgetPlan)
        .filter(models.BudgetPlan.client_id == client_id)
        .order_by(models.BudgetPlan.sort_order, models.BudgetPlan.id)
        .all()
    )
    return plans


def create_plan(
    db: Session, client_id: int, payload, *, commit: bool = True,
) -> models.BudgetPlan:
    data = _payload_data(payload)
    existing = db.query(models.BudgetPlan).filter_by(client_id=client_id, name=data["name"]).first()
    if existing:
        raise ValueError("A plan with this name already exists")
    plan = models.BudgetPlan(
        client_id=client_id,
        name=data["name"],
        description=data.get("description"),
        is_default=False,
        sort_order=data.get("sort_order", 0),
    )
    db.add(plan)
    _save_plan(db, plan, commit=commit)
    return plan


def update_plan(
    db: Session, client_id: int, plan_id: int, patch, *, commit: bool = True,
) -> models.BudgetPlan | None:
    plan = db.query(models.BudgetPlan).filter_by(id=plan_id, client_id=client_id).first()
    if not plan:
        return None
    data = _payload_data(patch)
    if data.get("name") is not None:
        duplicate = db.query(models.BudgetPlan).filter(
            models.BudgetPlan.client_id == client_id,
            models.BudgetPlan.name == data["name"],
            models.BudgetPlan.id != plan_id,
        ).first()
        if duplicate:
            raise ValueError("A plan with this name already exists")
        plan.name = data["name"]
    for key in ("description", "sort_order"):
        if data.get(key) is not None:
            setattr(plan, key, data[key])
    _save_plan(db, plan, commit=commit)
    return plan


def _save_plan(db: Session, plan: models.BudgetPlan, *, commit: bool) -> None:
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("A plan with this name already exists") from exc
    if commit:
        db.refresh(plan)


def delete_plan(
    db: Session, client_id: int, plan_id: int, *, commit: bool = True,
) -> bool:
    plan = db.query(models.BudgetPlan).filter_by(id=plan_id, client_id=client_id).first()
    if not plan:
        return False
    if plan.is_default:
        raise ValueError("Cannot delete the default plan")
    # X5: the plan's lines go with it. This used to deactivate them and let the
    # foreign key null their plan_id, which left rows no reader could see --
    # every query filters on is_active -- and that no longer said which plan
    # they had belonged to. The export carries plan lines without that filter,
    # so they came back from a backup as untraceable orphans. A plan is a
    # container and its lines are its contents; discarding the container while
    # keeping the contents in no container holds less information than either.
    db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id == plan_id,
    ).delete(synchronize_session=False)
    db.delete(plan)
    if commit:
        db.commit()
    else:
        db.flush()
    return True


def delete_plan_line(
    db: Session, client_id: int, line_id: int, *, commit: bool = True,
) -> bool:
    line = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.id == line_id,
        models.MonthlyPlanLine.client_id == client_id,
    ).first()
    if not line:
        return False
    # X13: DELETE removes the line, for the same reason as X2 and X5. is_active
    # keeps its other two jobs -- the deduplication repair and copy-period
    # replacement both use it to mark a line superseded -- so the flag still
    # means something; it is just no longer what deleting does behind the
    # caller's back.
    removed = line
    db.delete(line)
    sync_capsule_monthly_contributions(db, client_id, [removed])
    if commit:
        db.commit()
    else:
        db.flush()
    return True


def get_or_create_default_plan(db: Session, client_id: int, *, commit: bool = True) -> models.BudgetPlan:
    # Write path only: it creates the default plan and repairs a client that
    # somehow has two. It no longer adopts orphan plan lines: X5 removed the
    # only thing that produced them, and data_health_service's repair -- the
    # right home for a repair -- already performs that update itself.
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
        if commit:
            db.commit()
            db.refresh(plan)
        else:
            db.flush()
    elif len(defaults) > 1:
        for extra in defaults[1:]:
            extra.is_default = False
        db.add(plan)
        db.commit()
        db.refresh(plan)
    return plan


def replace_plan_lines_from_plan(
    db: Session,
    client_id: int,
    target_plan_id: int,
    source_plan_id: int,
    *,
    source_period: str | None = None,
    target_period: str | None = None,
    commit: bool = False,
) -> int:
    if (source_period is None) != (target_period is None):
        raise ValueError("Source and target periods must be supplied together")
    if target_plan_id == source_plan_id and source_period is None:
        return 0

    target_plan = db.query(models.BudgetPlan).filter_by(id=target_plan_id, client_id=client_id).first()
    if not target_plan:
        raise ValueError("Target budget plan not found")
    source_plan = db.query(models.BudgetPlan).filter_by(id=source_plan_id, client_id=client_id).first()
    if not source_plan:
        raise ValueError("Source budget plan not found")

    source_query = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.plan_id == source_plan_id,
            models.MonthlyPlanLine.is_active.is_(True),
        )
    )
    if source_period is not None:
        source_query = source_query.filter(models.MonthlyPlanLine.target_period == source_period)
    source_lines = source_query.all()

    target_query = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.plan_id == target_plan_id,
        )
    )
    if target_period is not None:
        target_query = target_query.filter(models.MonthlyPlanLine.target_period == target_period)
    # Period copying historically synchronizes loaded rows, while plan copying does not.
    target_query.update({"is_active": False}, synchronize_session="auto" if target_period is not None else False)

    for src in source_lines:
        new_line = models.MonthlyPlanLine(
            client_id=client_id,
            plan_id=target_plan_id,
            target_period=target_period if target_period is not None else src.target_period,
            line_type=src.line_type,
            target_type=src.target_type,
            target_id=src.target_id,
            account_id=src.account_id,
            source_account_id=src.source_account_id,
            name=src.name,
            amount_minor=src.amount_minor,
            source=src.source,
            source_kind=src.source_kind,
            manual_override=src.manual_override,
            cash_treatment=src.cash_treatment,
            is_active=True,
        )
        assign_plan_line_identity(new_line)
        db.add(new_line)
    if commit:
        db.commit()
    return len(source_lines)




def find_budget_plan_id(db: Session, client_id: int, plan_id: int | None = None) -> int | None:
    """Read-path resolver: the plan a read should use, or None if there is none.

    Its write-path twin below creates the default plan when a client has none,
    which is why a read cannot call it: X9 was eight read endpoints inserting a
    budget_plans row. "This client has no plan" is a shape the callers render
    -- no planned figures, actuals untouched -- not an error.

    An explicitly requested plan that does not belong to this client is still
    an error, and it is the same error the write path raises.
    """
    if plan_id is not None:
        if get_plan(db, client_id, plan_id) is None:
            raise ValueError("Budget plan not found")
        return plan_id
    plan = (
        db.query(models.BudgetPlan)
        .filter(models.BudgetPlan.client_id == client_id)
        .order_by(
            # The same preference get_or_create_default_plan applies: the
            # default first, then the client's own ordering.
            models.BudgetPlan.is_default.desc(),
            models.BudgetPlan.sort_order,
            models.BudgetPlan.id,
        )
        .first()
    )
    return plan.id if plan is not None else None


def resolve_budget_plan_id(db: Session, client_id: int, plan_id: int | None = None, *, commit: bool = True) -> int:
    """Write-path resolver: may create the default plan the caller will write into."""
    if plan_id is None:
        return get_or_create_default_plan(db, client_id, commit=commit).id
    find_budget_plan_id(db, client_id, plan_id)
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
    for key, value in minor_fields(data, money_client_currency(db, client_id), "amount").items():
        if key != "id":
            setattr(line, key, value)
    line.source_kind = _line_source_kind(line)
    if line.source == "manual":
        line.source_kind = "manual"
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
            funding_accounts = {source.account_id for source in capsule.funding_sources}
            if line.account_id is not None:
                allowed = funding_accounts
                if line.account_id not in allowed:
                    raise Invalid(f"Account {line.account_id} is not a funding account of capsule {capsule.id} ({capsule.name})")
            elif len(funding_accounts) > 1:
                raise Invalid(f"Capsule {capsule.id} ({capsule.name}) has several funding accounts; account_id is required")
            elif funding_accounts:
                line.account_id = next(iter(funding_accounts))
            if line.source in {None, "manual", "capsule"}:
                line.source_kind = "capsule"
    assign_plan_line_identity(line)


def sync_capsule_monthly_contributions(
    db: Session, client_id: int, lines: Sequence[models.MonthlyPlanLine],
) -> None:
    """A capsule's monthly contribution is the sum of its allocation rows.

    One row per funding account (D2), so the figure can no longer be the row
    that happened to be saved last. Scoped to one plan and period, because an
    alternative scenario's rows are a different intent and must not add to it.

    Called after the batch is flushed so one query sees every row, rather than
    reconstructing the batch from the session's pending sets while it is still
    being built.
    """
    touched = {
        (line.target_id, line.plan_id, line.target_period)
        for line in lines
        if line.target_type == "capsule" and line.target_id
        and line.line_type == "allocation"
    }
    if not touched:
        return
    db.flush()
    for capsule_id, plan_id, period in sorted(touched):
        capsule = db.query(models.Capsule).filter_by(
            id=capsule_id, client_id=client_id,
        ).first()
        if capsule is None:
            continue
        capsule.monthly_contribution_minor = int(db.query(
            func.coalesce(func.sum(models.MonthlyPlanLine.amount_minor), 0),
        ).filter_by(
            client_id=client_id, plan_id=plan_id, target_period=period,
            target_type="capsule", target_id=capsule_id,
            line_type="allocation", is_active=True,
        ).scalar())


def active_lines_for_periods(
    db: Session, client_id: int, plan_id: int | None, periods: Sequence[str],
) -> list[models.MonthlyPlanLine]:
    """The stored active rows of one plan in these months; none when there is no plan yet."""
    if plan_id is None or not periods:
        return []
    return db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id == plan_id,
        models.MonthlyPlanLine.target_period.in_(list(periods)),
        models.MonthlyPlanLine.is_active.is_(True),
    ).order_by(models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id).all()


def retire_plan_lines(db: Session, client_id: int, line_ids: Sequence[int], *, commit: bool = True) -> int:
    """Mark rows superseded (is_active false) without revalidating them.

    A row being replaced may no longer satisfy today's rules -- an account-less
    capsule row whose capsule now has several funding accounts -- and retiring
    it must not depend on that. Capsule contributions are re-summed afterwards.
    """
    rows = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.id.in_(list(line_ids)),
        models.MonthlyPlanLine.is_active.is_(True),
    ).all()
    for row in rows:
        row.is_active = False
    sync_capsule_monthly_contributions(db, client_id, rows)
    if commit:
        db.commit()
    else:
        db.flush()
    return len(rows)


def create_plan_lines(
    db: Session, client_id: int, payloads: list, *, commit: bool = True,
) -> list[models.MonthlyPlanLine]:
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
    sync_capsule_monthly_contributions(db, client_id, created)
    if not commit:
        db.flush()
        return created
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
    sync_capsule_monthly_contributions(db, client_id, saved)
    if commit:
        db.commit()
        for line in saved:
            db.refresh(line)
    else:
        db.flush()
    return saved
