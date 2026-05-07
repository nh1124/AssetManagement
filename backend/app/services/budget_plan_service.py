"""Monthly cash-flow planning and budget summary helpers."""
from __future__ import annotations

from datetime import date
from typing import Iterable

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import models
from .capsule_service import capsule_balance
from .fx_service import calculate_account_valued_balance, convert_amount, convert_transaction_amount
from .goal_service import get_life_events_with_progress


LIQUID_ACCOUNT_NAMES = {"cash", "bank", "savings"}
INFLOW_LINE_TYPES = {"income", "borrowing", "drawdown"}
OUTFLOW_LINE_TYPES = {"expense", "allocation", "debt_payment"}


def period_to_range(period: str) -> tuple[date, date]:
    year, month = [int(part) for part in period.split("-")]
    start = date(year, month, 1)
    end = start + relativedelta(months=1)
    return start, end


def add_months(period: str, months: int) -> str:
    start, _ = period_to_range(period)
    shifted = start + relativedelta(months=months)
    return f"{shifted.year}-{shifted.month:02d}"


def _month_matches_recurring(rec: models.RecurringTransaction, period_start: date) -> bool:
    if rec.frequency == "Monthly":
        return True
    if rec.frequency == "Yearly":
        return rec.month_of_year == period_start.month if rec.month_of_year else True
    return False


def _recurring_in_period_range(rec: models.RecurringTransaction, period: str) -> bool:
    if rec.start_period and period < rec.start_period:
        return False
    if rec.end_period and period > rec.end_period:
        return False
    return True


def _recurring_applies_to_period(rec: models.RecurringTransaction, period: str) -> bool:
    period_start, _ = period_to_range(period)
    return bool(rec.is_active) and _recurring_in_period_range(rec, period) and _month_matches_recurring(rec, period_start)


def _recurring_amount_for_period(rec: models.RecurringTransaction, period_start: date) -> float:
    if rec.frequency == "Monthly":
        return rec.amount or 0.0
    if rec.frequency == "Yearly":
        if rec.month_of_year:
            return rec.amount or 0.0 if rec.month_of_year == period_start.month else 0.0
        return (rec.amount or 0.0) / 12
    return 0.0


def recurring_totals(db: Session, client_id: int, period: str) -> dict[str, float]:
    period_start, _ = period_to_range(period)
    rows = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == client_id,
        models.RecurringTransaction.is_active.is_(True),
    ).all()
    totals = {
        "income": 0.0,
        "fixed_costs": 0.0,
        "debt_payments": 0.0,
        "allocations": 0.0,
        "borrowing": 0.0,
    }
    for rec in rows:
        if not _recurring_in_period_range(rec, period) or not _month_matches_recurring(rec, period_start):
            continue
        amount = convert_amount(
            db,
            client_id,
            _recurring_amount_for_period(rec, period_start),
            rec.currency,
            as_of_date=period_start,
        )
        tx_type = (rec.type or "").lower()
        if tx_type == "income":
            totals["income"] += amount
        elif tx_type in {"expense", "creditexpense"}:
            totals["fixed_costs"] += amount
        elif tx_type == "liabilitypayment":
            totals["debt_payments"] += amount
        elif tx_type in {"transfer", "creditassetpurchase"}:
            totals["allocations"] += amount
        elif tx_type == "borrowing":
            totals["borrowing"] += amount
    return totals


def _target_name_maps(db: Session, client_id: int) -> dict[str, dict[int, str]]:
    accounts = db.query(models.Account).filter(models.Account.client_id == client_id).all()
    capsules = db.query(models.Capsule).filter(models.Capsule.client_id == client_id).all()
    life_events = db.query(models.LifeEvent).filter(models.LifeEvent.client_id == client_id).all()
    products = db.query(models.Product).filter(models.Product.client_id == client_id).all()
    return {
        "account": {item.id: item.name for item in accounts},
        "capsule": {item.id: item.name for item in capsules},
        "life_event": {item.id: item.name for item in life_events},
        "product": {item.id: item.name for item in products},
    }


def _line_display_name(line: models.MonthlyPlanLine, name_maps: dict[str, dict[int, str]]) -> str:
    if line.name:
        return line.name
    if line.target_type == "account" and line.account_id:
        return name_maps["account"].get(line.account_id, "Account")
    if line.target_id:
        return name_maps.get(line.target_type, {}).get(line.target_id, line.target_type.title())
    return line.line_type.replace("_", " ").title()


def _period_transactions(db: Session, client_id: int, period: str) -> list[models.Transaction]:
    start, end = period_to_range(period)
    return db.query(models.Transaction).filter(
        models.Transaction.client_id == client_id,
        models.Transaction.date >= start,
        models.Transaction.date < end,
    ).all()


def _sum_transactions(txs: Iterable[models.Transaction], db: Session, client_id: int) -> float:
    return sum(convert_transaction_amount(db, tx, client_id=client_id) for tx in txs)


def actual_for_plan_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine | dict,
    period: str,
    capsule_accounts: dict[int, int | None] | None = None,
) -> float:
    capsule_accounts = capsule_accounts or {}
    txs = _period_transactions(db, client_id, period)
    line_type = line["line_type"] if isinstance(line, dict) else line.line_type
    target_type = line["target_type"] if isinstance(line, dict) else line.target_type
    target_id = line.get("target_id") if isinstance(line, dict) else line.target_id
    account_id = line.get("account_id") if isinstance(line, dict) else line.account_id
    name = (line.get("name") if isinstance(line, dict) else line.name) or ""
    needle = name.lower()

    if target_type == "capsule" and target_id:
        capsule = db.query(models.Capsule).filter(
            models.Capsule.id == target_id,
            models.Capsule.client_id == client_id,
        ).first()
        if capsule and line_type == "allocation":
            return capsule_balance(db, capsule)
        account_id = capsule_accounts.get(target_id)

    if line_type == "income":
        selected = [
            tx for tx in txs
            if tx.type == "Income"
            and (
                (account_id and tx.from_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
                or (not account_id and needle and needle in (tx.category or "").lower())
            )
        ]
    elif line_type == "expense":
        selected = [
            tx for tx in txs
            if tx.type in {"Expense", "CreditExpense"}
            and (
                (account_id and tx.to_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
                or (not account_id and needle and needle in (tx.category or "").lower())
            )
        ]
    elif line_type == "allocation":
        selected = [
            tx for tx in txs
            if tx.type in {"Transfer", "CreditAssetPurchase"}
            and (
                (account_id and tx.to_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
            )
        ]
    elif line_type == "debt_payment":
        selected = [
            tx for tx in txs
            if tx.type == "LiabilityPayment"
            and (
                (account_id and tx.to_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
            )
        ]
    elif line_type == "borrowing":
        selected = [
            tx for tx in txs
            if tx.type == "Borrowing"
            and (
                (account_id and tx.from_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
            )
        ]
    elif line_type == "drawdown":
        selected = [
            tx for tx in txs
            if tx.type == "Transfer"
            and (
                (account_id and tx.from_account_id == account_id)
                or (not account_id and needle and needle in (tx.description or "").lower())
            )
        ]
    else:
        selected = []
    return _sum_transactions(selected, db, client_id)


def _serialize_plan_line(
    db: Session,
    client_id: int,
    line: models.MonthlyPlanLine,
    name_maps: dict[str, dict[int, str]],
    capsule_accounts: dict[int, int | None],
) -> dict:
    actual = actual_for_plan_line(db, client_id, line, line.target_period, capsule_accounts)
    target_name = _line_display_name(line, name_maps)
    return {
        "id": line.id,
        "target_period": line.target_period,
        "line_type": line.line_type,
        "target_type": line.target_type,
        "target_id": line.target_id,
        "account_id": line.account_id,
        "source_account_id": line.source_account_id,
        "name": line.name,
        "target_name": target_name,
        "account_name": name_maps["account"].get(line.account_id) if line.account_id else None,
        "source_account_name": name_maps["account"].get(line.source_account_id) if line.source_account_id else None,
        "amount": round(line.amount or 0.0, 0),
        "planned_date": line.planned_date.isoformat() if line.planned_date else None,
        "actual": round(actual, 0),
        "variance": round((line.amount or 0.0) - actual, 0),
        "recurring_amount": 0.0,
        "priority": line.priority,
        "note": line.note,
        "is_active": line.is_active,
        "source": line.source or "manual",
        "recurring_transaction_id": line.recurring_transaction_id,
        "sync_status": None,
    }


def _virtual_capsule_line(
    db: Session,
    client_id: int,
    capsule: models.Capsule,
    period: str,
    capsule_accounts: dict[int, int | None],
) -> dict:
    line = {
        "id": None,
        "target_period": period,
        "line_type": "allocation",
        "target_type": "capsule",
        "target_id": capsule.id,
        "account_id": capsule.account_id,
        "source_account_id": None,
        "name": capsule.name,
        "target_name": capsule.name,
        "account_name": capsule.account.name if capsule.account else None,
        "source_account_name": None,
        "amount": round(capsule.monthly_contribution or 0.0, 0),
        "planned_date": None,
        "recurring_amount": 0.0,
        "priority": 2,
        "note": None,
        "is_active": True,
        "source": "capsule",
        "recurring_transaction_id": None,
        "sync_status": None,
    }
    actual = actual_for_plan_line(db, client_id, line, period, capsule_accounts)
    line["actual"] = round(actual, 0)
    line["variance"] = round((capsule.monthly_contribution or 0.0) - actual, 0)
    return line


def _sum_lines(lines: Iterable[dict], *line_types: str) -> float:
    wanted = set(line_types)
    return sum((line.get("amount") or 0.0) for line in lines if line.get("line_type") in wanted)


def _sum_actual(lines: Iterable[dict], *line_types: str) -> float:
    wanted = set(line_types)
    return sum((line.get("actual") or 0.0) for line in lines if line.get("line_type") in wanted)


def _recurring_line_type(rec: models.RecurringTransaction) -> str | None:
    tx_type = (rec.type or "").lower()
    if tx_type == "income":
        return "income"
    if tx_type == "borrowing":
        return "borrowing"
    if tx_type in {"expense", "creditexpense"}:
        return "expense"
    if tx_type in {"transfer", "creditassetpurchase"}:
        return "allocation"
    if tx_type == "liabilitypayment":
        return "debt_payment"
    return None


def _recurring_account_id(rec: models.RecurringTransaction, line_type: str) -> int | None:
    if line_type in {"income", "borrowing", "drawdown"}:
        return rec.from_account_id
    return rec.to_account_id


def _plan_match_key(line_type: str | None, target_type: str | None, account_id: int | None, name: str | None) -> tuple:
    normalized_name = "" if account_id else (name or "").strip().lower()
    return (line_type or "", target_type or "manual", account_id or 0, normalized_name)


def _recurring_plan_line(
    db: Session,
    rec: models.RecurringTransaction,
    period: str,
    name_maps: dict[str, dict[int, str]],
) -> dict | None:
    if not _recurring_applies_to_period(rec, period):
        return None
    line_type = _recurring_line_type(rec)
    if not line_type:
        return None
    period_start, _ = period_to_range(period)
    amount = convert_amount(
        db,
        rec.client_id,
        _recurring_amount_for_period(rec, period_start),
        rec.currency,
        as_of_date=period_start,
    )
    account_id = _recurring_account_id(rec, line_type)
    return {
        "id": None,
        "target_period": period,
        "line_type": line_type,
        "target_type": "account" if account_id else "manual",
        "target_id": None,
        "account_id": account_id,
        "source_account_id": rec.from_account_id if line_type in {"expense", "allocation", "debt_payment"} else rec.to_account_id,
        "name": rec.name,
        "target_name": name_maps["account"].get(account_id, rec.name) if account_id else rec.name,
        "account_name": name_maps["account"].get(account_id) if account_id else None,
        "source_account_name": name_maps["account"].get(rec.from_account_id) if rec.from_account_id else None,
        "amount": 0.0,
        "planned_date": None,
        "actual": 0.0,
        "variance": 0.0,
        "recurring_amount": round(amount, 0),
        "priority": 2,
        "note": None,
        "source": "recurrence",
        "recurring_transaction_id": rec.id,
        "recurring_transaction_ids": [rec.id],
        "recurring_items": [{
            "id": rec.id,
            "name": rec.name,
            "amount": round(amount, 0),
            "original_amount": round(rec.amount or 0.0, 0),
            "currency": rec.currency,
        }],
        "sync_status": "missing",
        "is_active": True,
    }


def recurring_plan_lines(db: Session, client_id: int, period: str) -> list[dict]:
    name_maps = _target_name_maps(db, client_id)
    recurrences = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == client_id,
        models.RecurringTransaction.is_active.is_(True),
    ).all()
    lines = [line for rec in recurrences if (line := _recurring_plan_line(db, rec, period, name_maps)) is not None]
    aggregated: dict[tuple, dict] = {}
    for line in lines:
        key = _plan_match_key(line["line_type"], line["target_type"], line["account_id"], line["name"])
        if key not in aggregated:
            item = dict(line)
            if item["account_id"]:
                item["name"] = item["account_name"] or item["target_name"]
                item["target_name"] = item["account_name"] or item["target_name"]
            aggregated[key] = item
            continue
        existing = aggregated[key]
        existing["recurring_amount"] = round((existing.get("recurring_amount") or 0.0) + (line.get("recurring_amount") or 0.0), 0)
        existing["recurring_transaction_ids"] = [
            *existing.get("recurring_transaction_ids", []),
            *line.get("recurring_transaction_ids", []),
        ]
        existing["recurring_items"] = [
            *existing.get("recurring_items", []),
            *line.get("recurring_items", []),
        ]
    return list(aggregated.values())


def _merge_recurring_context(plan_lines: list[dict], recurrence_lines: list[dict]) -> list[dict]:
    recurrence_by_id = {
        recurring_id: line
        for line in recurrence_lines
        for recurring_id in line.get("recurring_transaction_ids", [line.get("recurring_transaction_id")])
        if recurring_id is not None
    }
    recurrence_by_key = {
        _plan_match_key(line["line_type"], line["target_type"], line["account_id"], line["name"]): line
        for line in recurrence_lines
    }
    matched_recurring_ids: set[int] = set()

    for line in plan_lines:
        recurring = None
        recurring_id = line.get("recurring_transaction_id")
        linked_by_id = False
        if recurring_id:
            recurring = recurrence_by_id.get(recurring_id)
            linked_by_id = recurring is not None
        if not recurring:
            recurring = recurrence_by_key.get(
                _plan_match_key(line.get("line_type"), line.get("target_type"), line.get("account_id"), line.get("name") or line.get("target_name"))
            )
        recurring_amount = round((recurring or {}).get("recurring_amount") or 0.0, 0)
        if recurring:
            matched_recurring_ids.update(recurring.get("recurring_transaction_ids", [recurring["recurring_transaction_id"]]))
            line["recurring_transaction_id"] = line.get("recurring_transaction_id") or recurring["recurring_transaction_id"]
            line["recurring_transaction_ids"] = recurring.get("recurring_transaction_ids", [recurring["recurring_transaction_id"]])
            line["recurring_items"] = recurring.get("recurring_items", [])
        line["recurring_amount"] = recurring_amount
        if not recurring:
            line["sync_status"] = None
        elif line.get("source") == "recurrence" and round(line.get("amount") or 0.0, 0) == recurring_amount:
            line["sync_status"] = "synced"
        else:
            line["sync_status"] = "diff"

    plan_lines.extend([
        line for line in recurrence_lines
        if not set(line.get("recurring_transaction_ids", [line["recurring_transaction_id"]])).intersection(matched_recurring_ids)
    ])
    return plan_lines


def _liquid_cash(db: Session, client_id: int) -> float:
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "asset",
        models.Account.is_active.is_(True),
        or_(models.Account.name.in_(LIQUID_ACCOUNT_NAMES), models.Account.role == "operating"),
    ).all()
    return sum(calculate_account_valued_balance(db, account) for account in accounts)


def get_budget_summary(
    db: Session,
    client_id: int,
    period: str,
    cash_flow_start_period: str | None = None,
    cash_flow_months: int = 12,
) -> dict:
    events_with_progress = get_life_events_with_progress(db, client_id=client_id)
    total_gap = sum(max(0, e["gap"]) for e in events_with_progress)
    avg_years = (
        sum(e["years_remaining"] for e in events_with_progress) / len(events_with_progress)
        if events_with_progress else 10
    )
    required_monthly_savings = total_gap / (avg_years * 12) if avg_years > 0 else 0

    recurring = recurring_totals(db, client_id, period)
    name_maps = _target_name_maps(db, client_id)
    capsules = db.query(models.Capsule).filter(models.Capsule.client_id == client_id).all()
    capsule_accounts = {capsule.id: capsule.account_id for capsule in capsules}
    capsule_by_life_event_id = {
        capsule.life_event_id: capsule
        for capsule in capsules
        if capsule.life_event_id
    }

    plan_models = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.target_period == period,
        models.MonthlyPlanLine.is_active.is_(True),
    ).order_by(models.MonthlyPlanLine.line_type, models.MonthlyPlanLine.priority, models.MonthlyPlanLine.id).all()
    plan_lines = [
        _serialize_plan_line(db, client_id, line, name_maps, capsule_accounts)
        for line in plan_models
    ]
    for line in plan_lines:
        if line.get("line_type") == "allocation" and line.get("target_type") == "life_event":
            capsule = capsule_by_life_event_id.get(line.get("target_id"))
            if capsule:
                line["target_type"] = "capsule"
                line["target_id"] = capsule.id
                line["account_id"] = capsule.account_id
                line["name"] = capsule.name
                line["target_name"] = capsule.name
                line["account_name"] = capsule.account.name if capsule.account else None
                actual = actual_for_plan_line(db, client_id, line, period, capsule_accounts)
                line["actual"] = round(actual, 0)
                line["variance"] = round((line.get("amount") or 0.0) - actual, 0)

    existing_capsule_ids = {
        line.get("target_id")
        for line in plan_lines
        if line.get("line_type") == "allocation" and line.get("target_type") == "capsule"
    }
    for capsule in capsules:
        if capsule.id not in existing_capsule_ids:
            plan_lines.append(_virtual_capsule_line(db, client_id, capsule, period, capsule_accounts))
    plan_lines = _merge_recurring_context(plan_lines, recurring_plan_lines(db, client_id, period))

    expense_lines = [line for line in plan_lines if line["line_type"] == "expense"]
    allocation_lines = [line for line in plan_lines if line["line_type"] == "allocation"]
    debt_lines = [line for line in plan_lines if line["line_type"] == "debt_payment"]
    inflow_lines = [line for line in plan_lines if line["line_type"] in INFLOW_LINE_TYPES]
    capsule_lines = [line for line in allocation_lines if line.get("target_type") == "capsule"]

    monthly_income = recurring["income"]
    total_income_plan = _sum_lines(inflow_lines, "income")
    total_borrowing_plan = _sum_lines(inflow_lines, "borrowing")
    total_drawdown_plan = _sum_lines(inflow_lines, "drawdown")
    total_expected_inflow = total_income_plan + total_borrowing_plan + total_drawdown_plan

    total_variable_budget = _sum_lines(expense_lines, "expense")
    total_allocation_plan = _sum_lines(allocation_lines, "allocation")
    total_debt_plan = _sum_lines(debt_lines, "debt_payment")
    total_capsule_plan = _sum_lines(capsule_lines, "allocation")
    total_capsule_actual = _sum_actual(capsule_lines, "allocation")

    remaining = (
        total_expected_inflow
        - total_variable_budget
        - total_allocation_plan
        - total_debt_plan
    )
    starting_cash = _liquid_cash(db, client_id)
    minimum_operating_cash = 0.0
    ending_cash_after_plan = starting_cash + remaining
    feasibility_status = "ok"
    if remaining < 0:
        feasibility_status = "warning"
    if ending_cash_after_plan < minimum_operating_cash:
        feasibility_status = "shortfall"

    projection_start = cash_flow_start_period or period
    projection = get_cash_flow_projection(db, client_id, projection_start, months=cash_flow_months, starting_cash=starting_cash)
    cash_flow_summary = summarize_cash_flow_projection(projection, starting_cash, projection_start)

    return {
        "period": period,
        "required_monthly_savings": round(required_monthly_savings, 0),
        "monthly_fixed_costs": round(recurring["fixed_costs"], 0),
        "monthly_income": round(monthly_income, 0),
        "recurring_debt_payments": round(recurring["debt_payments"], 0),
        "recurring_allocations": round(recurring["allocations"], 0),
        "recurring_borrowing": round(recurring["borrowing"], 0),
        "total_income_plan": round(total_income_plan, 0),
        "total_expected_inflow": round(total_expected_inflow, 0),
        "total_variable_budget": round(total_variable_budget, 0),
        "total_allocation_plan": round(total_allocation_plan, 0),
        "total_debt_plan": round(total_debt_plan, 0),
        "total_capsule_plan": round(total_capsule_plan, 0),
        "total_capsule_actual": round(total_capsule_actual, 0),
        "remaining_balance": round(remaining, 0),
        "starting_cash": round(starting_cash, 0),
        "ending_cash_after_plan": round(ending_cash_after_plan, 0),
        "minimum_operating_cash": round(minimum_operating_cash, 0),
        "feasibility_status": feasibility_status,
        "plan_lines": plan_lines,
        "expense_accounts": [
            {
                "id": line["id"] if line.get("source") == "one_time" and line.get("id") else line["account_id"] or line["id"] or -(line.get("recurring_transaction_id") or 0),
                "account_id": line["account_id"],
                "target_type": line.get("target_type"),
                "target_id": line.get("target_id"),
                "source_account_id": line.get("source_account_id"),
                "name": line["target_name"],
                "amount": line["amount"],
                "balance": line["actual"],
                "plan_line_id": line.get("id"),
                "planned_date": line.get("planned_date"),
                "priority": line.get("priority", 2),
                "note": line.get("note"),
                "recurring_amount": line.get("recurring_amount", 0.0),
                "source": line.get("source"),
                "sync_status": line.get("sync_status"),
                "recurring_transaction_id": line.get("recurring_transaction_id"),
                "recurring_transaction_ids": line.get("recurring_transaction_ids", []),
                "recurring_items": line.get("recurring_items", []),
            }
            for line in expense_lines
        ],
        "others_actual": 0,
        "sinking_funds": [
            {
                "id": line["target_id"] or line["id"] or 0,
                "name": line["target_name"],
                "life_event_id": None,
                "account_id": line["account_id"],
                "planned": line["amount"],
                "actual": line["actual"],
                "variance": line["variance"],
                "current_balance": round(
                    capsule_balance(db, capsule)
                    if (capsule := next((c for c in capsules if c.id == line.get("target_id")), None))
                    else 0.0,
                    0,
                ),
                "target_amount": round(
                    capsule.target_amount if (capsule := next((c for c in capsules if c.id == line.get("target_id")), None)) else 0.0,
                    0,
                ),
            }
            for line in capsule_lines
        ],
        "cash_flow_projection": projection,
        "cash_flow_summary": cash_flow_summary,
        "goals_count": len(events_with_progress),
        "total_goal_gap": round(total_gap, 0),
    }


def get_cash_flow_projection(
    db: Session,
    client_id: int,
    start_period: str,
    months: int = 12,
    starting_cash: float | None = None,
) -> list[dict]:
    cash = _liquid_cash(db, client_id) if starting_cash is None else starting_cash
    rows = []
    for idx in range(months):
        period = add_months(start_period, idx)
        lines = db.query(models.MonthlyPlanLine).filter(
            models.MonthlyPlanLine.client_id == client_id,
            models.MonthlyPlanLine.target_period == period,
            models.MonthlyPlanLine.is_active.is_(True),
        ).all()
        income = sum(
            line.amount or 0.0 for line in lines if line.line_type in INFLOW_LINE_TYPES
        )
        expense = sum(
            line.amount or 0.0 for line in lines if line.line_type == "expense"
        )
        allocation = sum(
            line.amount or 0.0 for line in lines if line.line_type == "allocation"
        )
        debt = sum(
            line.amount or 0.0 for line in lines if line.line_type == "debt_payment"
        )
        net = income - expense - allocation - debt
        cash += net
        setup_warnings = recurrence_setup_warnings(db, client_id, period, lines)
        rows.append({
            "period": period,
            "inflow": round(income, 0),
            "expense": round(expense, 0),
            "allocation": round(allocation, 0),
            "debt": round(debt, 0),
            "net_cash": round(net, 0),
            "ending_cash": round(cash, 0),
            "status": "shortfall" if cash < 0 else ("warning" if setup_warnings or net < 0 else "ok"),
            "setup_warnings": setup_warnings,
        })
    return rows


def recurrence_setup_warnings(
    db: Session,
    client_id: int,
    period: str,
    plan_models: list[models.MonthlyPlanLine],
) -> list[dict]:
    recurrence_lines = recurring_plan_lines(db, client_id, period)
    plan_by_recurring_id = {
        line.recurring_transaction_id: line
        for line in plan_models
        if line.recurring_transaction_id
    }
    plan_by_key = {
        _plan_match_key(line.line_type, line.target_type, line.account_id, line.name): line
        for line in plan_models
    }
    warnings = []
    for recurring_line in recurrence_lines:
        matched = plan_by_recurring_id.get(recurring_line["recurring_transaction_id"])
        if not matched:
            matched = plan_by_key.get(_plan_match_key(
                recurring_line["line_type"],
                recurring_line["target_type"],
                recurring_line["account_id"],
                recurring_line["name"],
            ))
        if not matched:
            warnings.append({
                "type": "missing_budget",
                "recurring_transaction_id": recurring_line["recurring_transaction_id"],
                "name": recurring_line["name"],
                "amount": recurring_line["recurring_amount"],
            })
            continue
        if round(matched.amount or 0.0, 0) != round(recurring_line["recurring_amount"], 0):
            warnings.append({
                "type": "amount_diff",
                "recurring_transaction_id": recurring_line["recurring_transaction_id"],
                "name": recurring_line["name"],
                "amount": recurring_line["recurring_amount"],
                "budget_amount": round(matched.amount or 0.0, 0),
            })
    return warnings


def summarize_cash_flow_projection(
    projection: list[dict],
    starting_cash: float,
    start_period: str,
) -> dict[str, float | int | str | None]:
    cash_points = [round(starting_cash, 0)] + [row["ending_cash"] for row in projection]
    lowest_cash = min(cash_points) if cash_points else round(starting_cash, 0)
    shortfall_month = start_period if starting_cash < 0 else None
    runway_months = 0 if starting_cash < 0 else len(projection)

    if starting_cash >= 0:
        for index, row in enumerate(projection):
            if row["ending_cash"] < 0:
                shortfall_month = row["period"]
                runway_months = index
                break

    return {
        "runway_months": runway_months,
        "lowest_cash": round(lowest_cash, 0),
        "required_buffer": round(max(0.0, -lowest_cash), 0),
        "shortfall_month": shortfall_month,
        "horizon_months": len(projection),
    }


def save_plan_lines(db: Session, client_id: int, payloads: list) -> list[models.MonthlyPlanLine]:
    saved: list[models.MonthlyPlanLine] = []
    for payload in payloads:
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
        line_id = data.pop("id", None)
        line = None
        if line_id:
            line = db.query(models.MonthlyPlanLine).filter(
                models.MonthlyPlanLine.id == line_id,
                models.MonthlyPlanLine.client_id == client_id,
            ).first()
        if not line:
            line = models.MonthlyPlanLine(client_id=client_id)
            db.add(line)
        for key, value in data.items():
            setattr(line, key, value)
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
        saved.append(line)
    db.commit()
    for line in saved:
        db.refresh(line)
    db.commit()
    return saved
