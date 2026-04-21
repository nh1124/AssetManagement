"""Reconcile Service - compare journal truth with denormalized account balances."""
from __future__ import annotations

from typing import List

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models


def calculate_true_balance(db: Session, account: models.Account) -> float:
    """
    Calculate account balance from journal entries only.
    - asset / expense: debit - credit
    - liability / income: credit - debit
    """
    result = db.query(
        func.sum(models.JournalEntry.debit).label("total_debit"),
        func.sum(models.JournalEntry.credit).label("total_credit"),
    ).filter(models.JournalEntry.account_id == account.id).first()

    total_debit = result.total_debit or 0.0
    total_credit = result.total_credit or 0.0

    if account.account_type in ("asset", "expense"):
        return total_debit - total_credit
    return total_credit - total_debit


def run_reconcile(db: Session, client_id: int, fix: bool = False) -> List[dict]:
    """Return discrepancies and optionally fix stored balances."""
    accounts = db.query(models.Account).filter(
        models.Account.client_id == client_id,
        models.Account.is_active.is_(True),
    ).all()

    discrepancies: List[dict] = []
    for account in accounts:
        true_balance = calculate_true_balance(db, account)
        stored_balance = account.balance or 0.0
        diff = abs(true_balance - stored_balance)

        if diff > 0.01:
            row = {
                "account_id": account.id,
                "account_name": account.name,
                "account_type": account.account_type,
                "stored_balance": round(stored_balance, 2),
                "calculated_balance": round(true_balance, 2),
                "difference": round(true_balance - stored_balance, 2),
                "fixed": False,
            }
            if fix:
                account.balance = true_balance
                row["fixed"] = True
            discrepancies.append(row)

    if fix and discrepancies:
        db.commit()
    return discrepancies
