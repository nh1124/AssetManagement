"""Reporting Service - statements, variance and flow aggregation.

Layer 4. Reads the ledger and the adopted budget plan to produce B/S, P/L,
budget variance, account flows and net-worth history. Sits above
budget_plan_service, which is why these functions do not live in
ledger_service.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from .. import models
from .budget_plan_store import resolve_budget_plan_id
from .fx_service import (
    build_rate_lookup,
    convert_amount_with_lookup,
    get_client_currency,
)
from .ledger_valuation import calculate_account_valued_balances, convert_transaction_amount
from .journal_legs import legs_in_range, primary_accounts, signed_delta, valued_sides
from .ledger_service import DEBIT_NORMAL_TYPES


def get_balance_sheet(
    db: Session,
    as_of_date: Optional[date] = None,
    client_id: int | None = None,
) -> dict:
    """
    Generate Balance Sheet snapshot for current client.
    """
    if as_of_date is None:
        as_of_date = date.today()

    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.is_active == True,
    ).all()

    assets = []
    liabilities = []
    balances = calculate_account_valued_balances(db, accounts, as_of_date)
    for acc in accounts:
        balance = balances.get(acc.id, 0.0)
        if acc.account_type in ("asset", "item"):
            assets.append({"name": acc.name, "balance": balance})
        elif acc.account_type == "liability":
            liabilities.append({"name": acc.name, "balance": abs(balance)})

    total_assets = sum(a["balance"] for a in assets)
    total_liabilities = sum(l["balance"] for l in liabilities)
    net_worth = total_assets - total_liabilities

    return {
        "as_of_date": as_of_date.isoformat(),
        "currency": get_client_currency(db, client_id),
        "assets": assets,
        "liabilities": liabilities,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
    }


def get_profit_loss_for_range(
    db: Session,
    start_date: date,
    end_date: date,
    client_id: int | None = None,
) -> dict:
    """Generate Profit & Loss statement for an inclusive date range.

    Grouped by the account each leg touched, not by the transaction's category
    string. The account is the ledger's own answer, and it is the only one that
    works once a transaction can hit several expense accounts at once.
    """
    income_by_category: dict[str, float] = {}
    expense_by_category: dict[str, float] = {}

    for leg in legs_in_range(
        db, client_id, start_date, end_date, account_types={"income", "expense"}
    ):
        name = leg.account.name or "Other"
        bucket = income_by_category if leg.account_type == "income" else expense_by_category
        bucket[name] = bucket.get(name, 0.0) + leg.signed

    total_income = sum(income_by_category.values())
    total_expense = sum(expense_by_category.values())
    net_pl = total_income - total_expense

    return {
        "period": f"{start_date.isoformat()}..{end_date.isoformat()}",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "income": [{"category": k, "amount": v} for k, v in income_by_category.items()],
        "expenses": [{"category": k, "amount": v} for k, v in expense_by_category.items()],
        "total_income": total_income,
        "total_expenses": total_expense,
        "net_profit_loss": net_pl,
    }


def get_profit_loss(db: Session, year: int, month: int, client_id: int | None = None) -> dict:
    """Generate Profit & Loss statement for a specific month and client."""
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    return get_profit_loss_for_range(db, start_date, end_date - date.resolution, client_id)


def get_profit_loss_rollup_for_range(
    db: Session,
    start_date: date,
    end_date: date,
    client_id: int | None = None,
) -> dict:
    """Generate P/L grouped by top-level parent account for an inclusive date range."""
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.is_active == True,
    ).all()
    account_by_id = {account.id: account for account in accounts}

    def root_name(account_id: int | None, fallback: str) -> str:
        account = account_by_id.get(account_id or -1)
        if not account:
            return fallback or "Other"
        seen = set()
        current = account
        while current.parent_id and current.parent_id not in seen and current.parent_id in account_by_id:
            seen.add(current.id)
            current = account_by_id[current.parent_id]
        return current.name or fallback or "Other"

    income_by_category: dict[str, float] = {}
    expense_by_category: dict[str, float] = {}
    for leg in legs_in_range(
        db, client_id, start_date, end_date, account_types={"income", "expense"}
    ):
        category = root_name(leg.account.id, leg.account.name or "Other")
        bucket = income_by_category if leg.account_type == "income" else expense_by_category
        bucket[category] = bucket.get(category, 0.0) + leg.signed

    total_income = sum(income_by_category.values())
    total_expense = sum(expense_by_category.values())
    return {
        "period": f"{start_date.isoformat()}..{end_date.isoformat()}",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "income": [{"category": k, "amount": v} for k, v in income_by_category.items()],
        "expenses": [{"category": k, "amount": v} for k, v in expense_by_category.items()],
        "total_income": total_income,
        "total_expenses": total_expense,
        "net_profit_loss": total_income - total_expense,
        "rollup": True,
    }


def get_profit_loss_rollup(db: Session, year: int, month: int, client_id: int | None = None) -> dict:
    """Generate P/L grouped by top-level parent account when hierarchy exists."""
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    return get_profit_loss_rollup_for_range(db, start_date, end_date - date.resolution, client_id)


def _period_months(start_date: date, end_date: date) -> list[str]:
    months = []
    cursor = date(start_date.year, start_date.month, 1)
    last = date(end_date.year, end_date.month, 1)
    while cursor <= last:
        months.append(f"{cursor.year}-{cursor.month:02d}")
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def get_variance_analysis_for_range(
    db: Session,
    start_date: date,
    end_date: date,
    client_id: int | None = None,
    plan_id: int | None = None,
) -> dict:
    """Compare actual spending vs summed monthly budgets over an inclusive range."""
    month_keys = _period_months(start_date, end_date)
    resolved_plan_id = resolve_budget_plan_id(db, client_id, plan_id) if client_id is not None else plan_id

    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.account_type == "expense",
        models.Account.is_active.is_(True),
    ).all()

    monthly_plan_lines = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.plan_id == resolved_plan_id,
        models.MonthlyPlanLine.target_period.in_(month_keys),
        models.MonthlyPlanLine.line_type == "expense",
        models.MonthlyPlanLine.is_active.is_(True),
    ).all()
    budget_map: dict[int, float] = {}
    for line in monthly_plan_lines:
        if line.account_id:
            budget_map[line.account_id] = budget_map.get(line.account_id, 0.0) + line.amount

    # Every expense leg names its own account, so the category fallback and the
    # orphan bucket it produced are gone. A leg on an inactive expense account
    # still has to be reported, or the actual total would silently shrink.
    actual_by_account_id: dict[int, float] = {}
    inactive_accounts: dict[int, models.Account] = {}
    for leg in legs_in_range(db, client_id, start_date, end_date, account_types={"expense"}):
        actual_by_account_id[leg.account.id] = actual_by_account_id.get(leg.account.id, 0.0) + leg.signed
        if not leg.account.is_active:
            inactive_accounts[leg.account.id] = leg.account

    variance_items = []
    for acc in accounts:
        actual = actual_by_account_id.get(acc.id, 0.0)
        budget = budget_map.get(acc.id, 0.0)
        variance_items.append(
            {
                "category": acc.name,
                "budget": budget,
                "actual": actual,
                "variance": budget - actual,
                "percentage": (actual / budget * 100) if budget > 0 else 0,
            }
        )

    for account_id, account in inactive_accounts.items():
        amount = actual_by_account_id.get(account_id, 0.0)
        variance_items.append(
            {
                "category": account.name,
                "budget": 0,
                "actual": amount,
                "variance": -amount,
                "percentage": 100,
            }
        )

    total_budget = sum(v["budget"] for v in variance_items)
    total_actual = sum(v["actual"] for v in variance_items)

    return {
        "period": f"{start_date.isoformat()}..{end_date.isoformat()}",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "plan_id": resolved_plan_id,
        "budget_months": month_keys,
        "items": variance_items,
        "total_budget": total_budget,
        "total_actual": total_actual,
        "total_variance": total_budget - total_actual,
    }


def get_variance_analysis(
    db: Session,
    year: int,
    month: int,
    client_id: int | None = None,
    plan_id: int | None = None,
) -> dict:
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    result = get_variance_analysis_for_range(db, start_date, end_date - date.resolution, client_id, plan_id)
    result["period"] = f"{year}-{month:02d}"
    return result


def _flow_bucket_for_day(day: date, grain: str) -> tuple[str, str, date, date]:
    if grain == "day":
        return day.isoformat(), day.isoformat(), day, day
    if grain == "week":
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
        return f"{start.isocalendar().year}-W{start.isocalendar().week:02d}", f"{start.isocalendar().year}-W{start.isocalendar().week:02d}", start, end
    if grain == "quarter":
        quarter = (day.month - 1) // 3 + 1
        start = date(day.year, (quarter - 1) * 3 + 1, 1)
        next_start = date(day.year + 1, 1, 1) if quarter == 4 else date(day.year, quarter * 3 + 1, 1)
        end = next_start - date.resolution
        return f"{day.year}-Q{quarter}", f"{day.year} Q{quarter}", start, end

    start = date(day.year, day.month, 1)
    end = date(day.year + 1, 1, 1) - date.resolution if day.month == 12 else date(day.year, day.month + 1, 1) - date.resolution
    return f"{day.year}-{day.month:02d}", f"{day.year}-{day.month:02d}", start, end


def _flow_buckets(start_date: date, end_date: date, grain: str) -> list[dict]:
    buckets: list[dict] = []
    seen: set[str] = set()
    cursor = start_date
    while cursor <= end_date:
        key, label, bucket_start, bucket_end = _flow_bucket_for_day(cursor, grain)
        if key not in seen:
            buckets.append(
                {
                    "key": key,
                    "label": label,
                    "start_date": max(bucket_start, start_date).isoformat(),
                    "end_date": min(bucket_end, end_date).isoformat(),
                }
            )
            seen.add(key)
        if grain == "day":
            cursor += timedelta(days=1)
        elif grain == "week":
            cursor += timedelta(days=7)
        elif grain == "quarter":
            next_month = ((cursor.month - 1) // 3 + 1) * 3 + 1
            cursor = date(cursor.year + 1, 1, 1) if next_month > 12 else date(cursor.year, next_month, 1)
        else:
            cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return buckets


def _valued_entry_sides(db: Session, entry: models.JournalEntry, tx: models.Transaction, client_id: int | None) -> tuple[float, float]:
    return valued_sides(db, entry, tx, client_id)


def _normal_balance_delta(account_type: str | None, debit: float, credit: float) -> float:
    return signed_delta(account_type, debit, credit)


def get_account_flows_for_range(
    db: Session,
    start_date: date,
    end_date: date,
    grain: str = "month",
    account_types: list[str] | None = None,
    include_zero: bool = False,
    client_id: int | None = None,
) -> dict:
    """Return debit/credit movement by account and time bucket for a date range."""
    if grain not in {"day", "week", "month", "quarter"}:
        raise ValueError("grain must be one of day, week, month, quarter")
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    normalized_types = {item for item in (account_types or []) if item}
    account_query = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.is_active.is_(True),
    )
    if normalized_types:
        account_query = account_query.filter(models.Account.account_type.in_(normalized_types))
    accounts = account_query.order_by(models.Account.account_type, models.Account.name).all()
    account_by_id = {account.id: account for account in accounts}
    buckets = _flow_buckets(start_date, end_date, grain)
    bucket_templates = {
        bucket["key"]: {
            "key": bucket["key"],
            "label": bucket["label"],
            "debit": 0.0,
            "credit": 0.0,
            "net_movement": 0.0,
            "normal_balance_delta": 0.0,
            "transaction_count": 0,
        }
        for bucket in buckets
    }

    rows = {
        account.id: {
            "account_id": account.id,
            "account_name": account.name,
            "account_type": account.account_type,
            "total_debit": 0.0,
            "total_credit": 0.0,
            "net_movement": 0.0,
            "normal_balance_delta": 0.0,
            "transaction_count": 0,
            "buckets": {key: dict(value) for key, value in bucket_templates.items()},
        }
        for account in accounts
    }

    entries = db.query(models.JournalEntry, models.Transaction).join(
        models.Transaction,
        models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(
        models.Transaction.client_id == client_id,
        models.Transaction.date >= start_date,
        models.Transaction.date <= end_date,
    )
    if account_by_id:
        entries = entries.filter(models.JournalEntry.account_id.in_(account_by_id.keys()))

    for entry, tx in entries.all():
        account = account_by_id.get(entry.account_id)
        if not account:
            continue
        debit, credit = _valued_entry_sides(db, entry, tx, client_id)
        normal_delta = _normal_balance_delta(account.account_type, debit, credit)
        key, _, _, _ = _flow_bucket_for_day(tx.date, grain)
        row = rows[account.id]
        row["total_debit"] += debit
        row["total_credit"] += credit
        row["net_movement"] += debit - credit
        row["normal_balance_delta"] += normal_delta
        row["transaction_count"] += 1
        bucket = row["buckets"][key]
        bucket["debit"] += debit
        bucket["credit"] += credit
        bucket["net_movement"] += debit - credit
        bucket["normal_balance_delta"] += normal_delta
        bucket["transaction_count"] += 1

    account_rows = []
    for row in rows.values():
        if include_zero or row["transaction_count"] > 0 or abs(row["normal_balance_delta"]) > 0.01:
            row["buckets"] = [row["buckets"][bucket["key"]] for bucket in buckets]
            account_rows.append(row)

    account_rows.sort(key=lambda row: (row["account_type"], -abs(row["normal_balance_delta"]), row["account_name"]))
    total_debit = sum(row["total_debit"] for row in account_rows)
    total_credit = sum(row["total_credit"] for row in account_rows)
    return {
        "period": f"{start_date.isoformat()}..{end_date.isoformat()}",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "grain": grain,
        "currency": get_client_currency(db, client_id),
        "account_types": sorted(normalized_types),
        "buckets": buckets,
        "accounts": account_rows,
        "totals": {
            "debit": total_debit,
            "credit": total_credit,
            "net_movement": total_debit - total_credit,
            "normal_balance_delta": sum(row["normal_balance_delta"] for row in account_rows),
            "account_count": len(account_rows),
        },
    }


def get_account_transactions_for_range(
    db: Session,
    account_id: int,
    start_date: date,
    end_date: date,
    limit: int = 100,
    offset: int = 0,
    client_id: int | None = None,
) -> dict:
    """Return journal-backed transaction rows for one account in a date range."""
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.client_id == client_id,
    ).first()
    if not account:
        raise LookupError("Account not found")

    query = db.query(models.JournalEntry, models.Transaction).join(
        models.Transaction,
        models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(
        models.JournalEntry.account_id == account_id,
        models.Transaction.client_id == client_id,
        models.Transaction.date >= start_date,
        models.Transaction.date <= end_date,
    )
    total = query.count()
    entries = query.order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).offset(offset).limit(limit).all()

    items = []
    for entry, tx in entries:
        debit, credit = _valued_entry_sides(db, entry, tx, client_id)
        tx_from, tx_to = primary_accounts(tx)
        counterparts = []
        for other in tx.journal_entries:
            if other.id == entry.id:
                continue
            other_account = other.account
            other_debit, other_credit = _valued_entry_sides(db, other, tx, client_id)
            counterparts.append(
                {
                    "account_id": other.account_id,
                    "account_name": other_account.name if other_account else None,
                    "account_type": other_account.account_type if other_account else None,
                    "debit": other_debit,
                    "credit": other_credit,
                }
            )
        items.append(
            {
                "entry_id": entry.id,
                "transaction_id": tx.id,
                "date": tx.date.isoformat(),
                "description": tx.description,
                "currency": tx.currency,
                "amount": convert_transaction_amount(db, tx, client_id=client_id) if tx.amount else 0.0,
                "raw_amount": tx.amount,
                "account_id": account.id,
                "account_name": account.name,
                "account_type": account.account_type,
                "debit": debit,
                "credit": credit,
                "raw_debit": entry.debit or 0.0,
                "raw_credit": entry.credit or 0.0,
                "normal_balance_delta": _normal_balance_delta(account.account_type, debit, credit),
                "counterpart_accounts": counterparts,
                "from_account_id": tx_from.id if tx_from else None,
                "from_account_name": tx_from.name if tx_from else None,
                "to_account_id": tx_to.id if tx_to else None,
                "to_account_name": tx_to.name if tx_to else None,
            }
        )

    return {
        "account": {
            "id": account.id,
            "name": account.name,
            "account_type": account.account_type,
        },
        "period": f"{start_date.isoformat()}..{end_date.isoformat()}",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency": get_client_currency(db, client_id),
        "items": items,
        "total": total,
    }


def _calc_net_worth_at(db: Session, client_id: int, as_of: date) -> dict:
    assets = 0.0
    liabilities = 0.0
    accounts = db.query(models.Account).filter(models.Account.client_id == client_id).all()
    balances = calculate_account_valued_balances(db, accounts, as_of_date=as_of)
    for account in accounts:
        balance = balances.get(account.id, 0.0)
        if account.account_type in ("asset", "item"):
            assets += balance
        elif account.account_type == "liability":
            liabilities += abs(balance)

    return {
        "assets": assets,
        "liabilities": liabilities,
        "net_worth": assets - liabilities,
    }


def get_net_worth_history(db: Session, client_id: int, months: int = 36) -> list[dict]:
    months = max(1, min(months, 240))
    today = date.today()
    periods = []
    for i in range(months - 1, -1, -1):
        target = today.replace(day=1) - relativedelta(months=i)
        periods.append(target + relativedelta(months=1, days=-1))

    accounts = db.query(models.Account).filter(models.Account.client_id == client_id).all()
    account_by_id = {account.id: account for account in accounts}
    balances = {account.id: 0.0 for account in accounts}
    latest_period = periods[-1]
    lookup = build_rate_lookup(db, client_id)
    entries = db.query(models.JournalEntry, models.Transaction).join(
        models.Transaction,
        models.Transaction.id == models.JournalEntry.transaction_id,
    ).filter(
        models.JournalEntry.account_id.in_(account_by_id.keys() or {-1}),
        models.Transaction.date <= latest_period,
    ).order_by(models.Transaction.date, models.JournalEntry.id).all()

    history = []
    entry_index = 0
    for eom in periods:
        while entry_index < len(entries) and entries[entry_index][1].date <= eom:
            entry, transaction = entries[entry_index]
            entry_index += 1
            account = account_by_id.get(entry.account_id)
            if not account:
                continue
            if account.account_type in DEBIT_NORMAL_TYPES:
                signed_amount = (entry.debit or 0.0) - (entry.credit or 0.0)
            else:
                signed_amount = (entry.credit or 0.0) - (entry.debit or 0.0)
            balances[account.id] += convert_amount_with_lookup(
                lookup,
                signed_amount,
                transaction.currency,
                transaction.date,
            )

        assets = 0.0
        liabilities = 0.0
        for account in accounts:
            balance = balances.get(account.id, 0.0)
            if account.account_type in ("asset", "item"):
                assets += balance
            elif account.account_type == "liability":
                liabilities += abs(balance)

        history.append(
            {
                "period": eom.strftime("%Y-%m"),
                "net_worth": round(assets - liabilities, 2),
                "assets": round(assets, 2),
                "liabilities": round(liabilities, 2),
            }
        )

    return history
