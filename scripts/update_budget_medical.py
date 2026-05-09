"""
医療・薬代の月次予算を ¥800 → ¥5,000 に更新するスクリプト
対象: client_id=2, account_id=141 (医療・薬代), line_type='expense'
"""
import os, sys
sys.stdin.reconfigure(encoding="utf-8")
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5434/finance_ide"

from backend.app.database import SessionLocal
from backend.app import models

CLIENT_ID = 2
MEDICAL_ACCOUNT_ID = 141  # 医療・薬代
NEW_BUDGET = 5000

db = SessionLocal()
try:
    lines = (
        db.query(models.MonthlyPlanLine)
        .filter(
            models.MonthlyPlanLine.client_id == CLIENT_ID,
            models.MonthlyPlanLine.account_id == MEDICAL_ACCOUNT_ID,
            models.MonthlyPlanLine.line_type == "expense",
        )
        .all()
    )

    if not lines:
        print("該当レコードなし。")
    else:
        for line in lines:
            old = line.amount
            line.amount = NEW_BUDGET
            print(f"  id={line.id} period={line.target_period} {old} → {NEW_BUDGET}")

        db.commit()
        print(f"\n合計 {len(lines)} 件更新しました。")

finally:
    db.close()
