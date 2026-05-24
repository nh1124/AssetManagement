"""One-off repair helper for legacy MonthlyPlanLine.source_account_id.

Dry-run by default. Run inside the backend container, for example:

    python -m app.maintenance.repair_plan_line_sources \
      --client-id 2 --period 2026-05 --account-name "美容・理容費"

Add --apply to persist updates.
"""
from __future__ import annotations

import argparse
import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal
from app.services.registry_service import registry_entry_amount_for_period


@dataclass
class SourceCandidate:
    source_account_id: int
    amount: float
    reason: str
    evidence: str


def period_range(period: str) -> tuple[date, date]:
    year_text, month_text = period.split("-", 1)
    year = int(year_text)
    month = int(month_text)
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def account_name(account_by_id: dict[int, models.Account], account_id: int | None) -> str:
    if not account_id:
        return "-"
    account = account_by_id.get(account_id)
    return account.name if account else f"id={account_id}"


def line_source_from_transaction(line: models.MonthlyPlanLine, tx: models.Transaction) -> int | None:
    if line.line_type == "expense":
        if tx.type in {"Expense", "CreditExpense"} and tx.to_account_id == line.account_id:
            return tx.from_account_id
        return None
    if line.line_type == "allocation":
        if tx.type in {"Transfer", "CreditAssetPurchase"} and tx.to_account_id == line.account_id:
            return tx.from_account_id
        return None
    if line.line_type == "debt_payment":
        if tx.type == "LiabilityPayment" and tx.to_account_id == line.account_id:
            return tx.from_account_id
        return None
    if line.line_type == "borrowing":
        if tx.type == "Borrowing" and tx.from_account_id == line.account_id:
            return tx.to_account_id
        return None
    if line.line_type == "drawdown":
        if tx.type == "Transfer" and tx.from_account_id == line.account_id:
            return tx.to_account_id
        return None
    return None


def infer_from_transactions(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    start, end = period_range(line.target_period)
    txs = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.client_id == line.client_id,
            models.Transaction.date >= start,
            models.Transaction.date <= end,
        )
        .all()
    )
    grouped: dict[int, dict[str, object]] = {}
    for tx in txs:
        source_account_id = line_source_from_transaction(line, tx)
        if not source_account_id:
            continue
        group = grouped.setdefault(source_account_id, {"amount": 0.0, "ids": []})
        group["amount"] = float(group["amount"]) + float(tx.amount or 0.0)
        group["ids"].append(tx.id)

    if len(grouped) != 1:
        return None

    source_account_id, data = next(iter(grouped.items()))
    ids = ",".join(str(tx_id) for tx_id in data["ids"])
    return SourceCandidate(
        source_account_id=source_account_id,
        amount=float(data["amount"]),
        reason="transactions",
        evidence=f"tx_ids={ids}",
    )


def infer_from_recurring(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    if not line.recurring_transaction_id:
        return None
    recurring = (
        db.query(models.RecurringTransaction)
        .filter(
            models.RecurringTransaction.id == line.recurring_transaction_id,
            models.RecurringTransaction.client_id == line.client_id,
        )
        .first()
    )
    if not recurring or not recurring.from_account_id:
        return None
    return SourceCandidate(
        source_account_id=recurring.from_account_id,
        amount=float(recurring.amount or 0.0),
        reason="recurring",
        evidence=f"recurring_id={recurring.id}",
    )


def infer_from_registry(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    if not line.account_id:
        return None
    start, _ = period_range(line.target_period)
    entries = (
        db.query(models.RegistryEntry)
        .filter(
            models.RegistryEntry.client_id == line.client_id,
            models.RegistryEntry.is_active.is_(True),
            models.RegistryEntry.budget_active.is_(True),
            models.RegistryEntry.line_type == line.line_type,
            models.RegistryEntry.budget_account_id == line.account_id,
            models.RegistryEntry.source_account_id.isnot(None),
        )
        .all()
    )

    grouped: dict[int, dict[str, object]] = defaultdict(lambda: {"amount": 0.0, "ids": []})
    for entry in entries:
        amount = registry_entry_amount_for_period(db, entry, line.target_period, start, line.client_id)
        if amount <= 0:
            continue
        group = grouped[entry.source_account_id]
        group["amount"] = float(group["amount"]) + float(amount)
        group["ids"].append(entry.id)

    if len(grouped) != 1:
        return None

    source_account_id, data = next(iter(grouped.items()))
    ids = ",".join(str(entry_id) for entry_id in data["ids"])
    return SourceCandidate(
        source_account_id=source_account_id,
        amount=float(data["amount"]),
        reason="registry",
        evidence=f"registry_entry_ids={ids}",
    )


def candidate_for_line(db: Session, line: models.MonthlyPlanLine) -> SourceCandidate | None:
    return (
        infer_from_recurring(db, line)
        or infer_from_registry(db, line)
        or infer_from_transactions(db, line)
    )


def resolve_account_id(db: Session, client_id: int, account_name_filter: str | None) -> int | None:
    if not account_name_filter:
        return None
    account = (
        db.query(models.Account)
        .filter(
            models.Account.client_id == client_id,
            models.Account.name == account_name_filter,
        )
        .one_or_none()
    )
    if not account:
        raise SystemExit(f"Account not found for client_id={client_id}: {account_name_filter}")
    return account.id


def build_query(db: Session, args: argparse.Namespace):
    account_id = args.account_id or resolve_account_id(db, args.client_id, args.account_name)
    query = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == args.client_id,
        models.MonthlyPlanLine.is_active.is_(True),
        models.MonthlyPlanLine.source_account_id.is_(None),
    )
    if args.line_id:
        query = query.filter(models.MonthlyPlanLine.id.in_(args.line_id))
    if args.period:
        query = query.filter(models.MonthlyPlanLine.target_period.in_(args.period))
    if args.plan_id:
        query = query.filter(models.MonthlyPlanLine.plan_id.in_(args.plan_id))
    if account_id:
        query = query.filter(models.MonthlyPlanLine.account_id == account_id)
    if args.line_type:
        query = query.filter(models.MonthlyPlanLine.line_type.in_(args.line_type))
    return query.order_by(models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument("--period", action="append", help="YYYY-MM. Can be passed multiple times.")
    parser.add_argument("--plan-id", action="append", type=int)
    parser.add_argument("--line-id", action="append", type=int)
    parser.add_argument("--line-type", action="append")
    parser.add_argument("--account-id", type=int)
    parser.add_argument("--account-name")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        accounts = {
            account.id: account
            for account in db.query(models.Account).filter(models.Account.client_id == args.client_id).all()
        }
        lines = build_query(db, args).all()
        print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} candidates={len(lines)}")

        updated = 0
        skipped = 0
        for line in lines:
            candidate = candidate_for_line(db, line)
            target = account_name(accounts, line.account_id)
            if not candidate:
                skipped += 1
                print(
                    f"SKIP line_id={line.id} period={line.target_period} "
                    f"type={line.line_type} target={target} amount={line.amount}: no single source"
                )
                continue

            source = account_name(accounts, candidate.source_account_id)
            print(
                f"{'UPDATE' if args.apply else 'WOULD'} line_id={line.id} "
                f"period={line.target_period} type={line.line_type} target={target} "
                f"amount={line.amount} -> source={source} "
                f"via={candidate.reason} inferred_amount={candidate.amount} {candidate.evidence}"
            )
            if args.apply:
                line.source_account_id = candidate.source_account_id
                updated += 1

        if args.apply:
            db.commit()
            print(f"committed updates={updated} skipped={skipped}")
        else:
            print(f"dry-run updates={updated} skipped={skipped}; rerun with --apply to persist")
    finally:
        db.close()


if __name__ == "__main__":
    main()
