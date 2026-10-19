"""Rebuild the test client (client 1) from nothing, through the HTTP API.

Wipes the signed-in client's data with an empty import, then records a small household:
accounts, three months of transactions, automatic transactions, a fixed asset and a consumable,
earmarks with a rule, a tracked currency, and a goal scenario with its contribution plan and
earmark settings. Only ever run it against the test client.

    python scripts/seed_test_client.py --base http://127.0.0.1:18100 --username admin --password ...
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(self, method: str, path: str, body=None):
        request = urllib.request.Request(
            self.base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.token}"} if self.token else {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode()
        except urllib.error.HTTPError as error:
            detail = error.read().decode()
            # A product save that moves an earmark's amounts asks for confirmation; this script confirms it.
            if error.code == 409 and "reserve_changes_unconfirmed" in detail and "reserve_fingerprint" not in path:
                fingerprint = json.loads(detail)["detail"]["fingerprint"]
                return self.call(method, f"{path}{'&' if '?' in path else '?'}reserve_fingerprint={fingerprint}", body)
            sys.exit(f"{method} {path} -> {error.code}: {detail[:600]}")
        return json.loads(text) if text else None

    get = lambda self, path: self.call("GET", path)  # noqa: E731
    post = lambda self, path, body=None: self.call("POST", path, body if body is not None else {})  # noqa: E731
    put = lambda self, path, body: self.call("PUT", path, body)  # noqa: E731


def months_back(today: date, count: int) -> list[date]:
    """The first day of each of the last `count` months, oldest first, ending with this month."""
    year, month = today.year, today.month
    firsts = []
    for _ in range(count):
        firsts.append(date(year, month, 1))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return firsts[::-1]


def seed_ledger(api: Api, today: date) -> dict:
    accounts: dict[str, int] = {}

    def account(name, kind, **card):
        accounts[name] = api.post("/accounts/", {"name": name, "account_type": kind, **card})["id"]

    for name in ("メイン銀行", "貯蓄口座", "証券口座", "現金", "備品"):
        account(name, "asset")
    account("クレジットカード", "liability", liability_closing_day=25, liability_payment_day=27, liability_payment_month_offset=1)
    account("奨学金", "liability")
    for name in ("給与", "賞与", "配当", "開始残高"):
        account(name, "income")
    for name in ("食費", "住居費", "水道光熱費", "通信費", "交通費", "日用品", "娯楽", "保険料", "減価償却費"):
        account(name, "expense")

    def tx(day: date, description: str, amount: float, source: str, destination: str):
        api.post("/transactions/", {"date": day.isoformat(), "description": description, "amount": amount,
                                    "from_account_id": accounts[source], "to_account_id": accounts[destination]})

    # The journal is the only balance: opening amounts are transactions from an opening subject.
    opening = date(2026, 3, 31)
    for name, amount in (("メイン銀行", 800000), ("貯蓄口座", 400000), ("証券口座", 1500000), ("現金", 30000)):
        tx(opening, "開始残高", amount, "開始残高", name)
    tx(opening, "奨学金の借入", 1200000, "奨学金", "メイン銀行")
    tx(date(2026, 4, 1), "ノートPC 購入", 240000, "メイン銀行", "備品")
    for first in months_back(today, 3):
        def on(day):
            return first.replace(day=day)
        if on(25) <= today:
            tx(on(25), "給与", 300000, "給与", "メイン銀行")
        if on(27) <= today:
            tx(on(27), "家賃", 85000, "メイン銀行", "住居費")
            tx(on(27), "カード引き落とし", 62000, "メイン銀行", "クレジットカード")
            tx(on(27), "奨学金返済", 15000, "メイン銀行", "奨学金")
        for day, amount in ((3, 8200), (10, 9100), (17, 7600)):
            if on(day) <= today:
                tx(on(day), "スーパー", amount, "クレジットカード", "食費")
        if on(12) <= today:
            tx(on(12), "電気・ガス", 11800, "クレジットカード", "水道光熱費")
            tx(on(12), "映画", 3600, "現金", "娯楽")
        if on(5) <= today:
            tx(on(5), "定期券", 9800, "メイン銀行", "交通費")
    tx(date(today.year, today.month, 1), "配当金", 12000, "配当", "証券口座")

    auto = [
        {"name": "給与", "kind": "income", "amount": 300000, "source_account_id": accounts["給与"], "destination_account_id": accounts["メイン銀行"],
         "budget_account_id": accounts["給与"], "repeat_mode": "indefinite", "frequency": "Monthly", "day_of_month": 25},
        {"name": "家賃", "kind": "expense", "amount": 85000, "source_account_id": accounts["メイン銀行"], "destination_account_id": accounts["住居費"],
         "budget_account_id": accounts["住居費"], "repeat_mode": "indefinite", "frequency": "Monthly", "day_of_month": 27},
        {"name": "スマホ代", "kind": "expense", "amount": 6000, "source_account_id": accounts["クレジットカード"], "destination_account_id": accounts["通信費"],
         "budget_account_id": accounts["通信費"], "repeat_mode": "indefinite", "frequency": "Monthly", "day_of_month": 10},
        {"name": "火災保険", "kind": "expense", "amount": 18000, "source_account_id": accounts["メイン銀行"], "destination_account_id": accounts["保険料"],
         "budget_account_id": accounts["保険料"], "repeat_mode": "count", "frequency": "Yearly", "month_of_year": 4, "day_of_month": 1, "repeat_count": 5},
        {"name": "奨学金返済", "kind": "debt", "amount": 15000, "source_account_id": accounts["メイン銀行"], "destination_account_id": accounts["奨学金"],
         "budget_account_id": accounts["奨学金"], "repeat_mode": "count", "frequency": "Monthly", "day_of_month": 27, "repeat_count": 80},
        {"name": "積立投資", "kind": "transfer", "amount": 30000, "source_account_id": accounts["メイン銀行"], "destination_account_id": accounts["証券口座"],
         "budget_account_id": accounts["証券口座"], "repeat_mode": "indefinite", "frequency": "Monthly", "day_of_month": 1},
        {"name": "貯蓄への振替", "kind": "transfer", "amount": 50000, "source_account_id": accounts["メイン銀行"], "destination_account_id": accounts["貯蓄口座"],
         "budget_account_id": accounts["貯蓄口座"], "repeat_mode": "indefinite", "frequency": "Monthly", "day_of_month": 26},
        {"name": "引越し費用", "kind": "expense", "amount": 120000, "source_account_id": accounts["メイン銀行"], "destination_account_id": accounts["住居費"],
         "budget_account_id": accounts["住居費"], "repeat_mode": "once", "start_date": "2026-12-15"},
    ]
    for row in auto:
        api.post("/auto-transactions/", {"currency": "JPY", "start_date": today.isoformat(), **row})

    capsules = {}
    for name, target, monthly, source in (("旅行", 300000, 20000, "貯蓄口座"), ("緊急予備費", 600000, 0, "メイン銀行"),
                                          ("結婚資金", 2000000, 30000, "貯蓄口座"), ("家電の買い替え", 0, 0, "貯蓄口座")):
        capsule = api.post("/capsules/", {"name": name, "target_amount": target, "monthly_contribution": monthly})
        api.put(f"/capsules/{capsule['id']}/funding-sources", [{"account_id": accounts[source], "target_amount": target}])
        capsules[name] = capsule["id"]
    api.post("/capsules/rules", {"capsule_id": capsules["旅行"], "trigger_type": "Income", "trigger_account_id": accounts["給与"],
                                 "source_mode": "transaction_account", "amount_type": "percentage", "amount_value": 5})

    api.post("/products/", {"name": "ノートPC", "is_asset": True, "last_unit_price": 240000, "purchase_price": 240000,
                            "purchase_date": "2026-04-01", "lifespan_months": 48, "budget_treatment": "auto",
                            "funding_capsule_id": capsules["家電の買い替え"], "auto_depreciation": True,
                            "depreciation_method": "straight_line", "depreciation_interval": "monthly",
                            "depreciation_expense_account_id": accounts["減価償却費"], "depreciation_asset_account_id": accounts["備品"]})
    api.post("/products/", {"name": "洗濯洗剤", "is_asset": False, "last_unit_price": 600, "units_per_purchase": 1,
                            "frequency_days": 30, "budget_treatment": "auto", "budget_account_id": accounts["日用品"]})
    api.post("/exchange-rates/tracked", {"currency": "USD"})
    return {"accounts": accounts, "capsules": capsules}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--client-id", type=int, default=1, help="refuse to run unless the signed-in client has this id")
    args = parser.parse_args()
    api = Api(args.base)
    auth = api.post("/auth/login", {"username": args.username, "password": args.password})
    if auth.get("client_id") != args.client_id:
        sys.exit(f"signed in as client {auth.get('client_id')}, expected {args.client_id}; nothing changed")
    api.token = auth["access_token"]
    exported = api.get("/data/export")
    api.post("/data/import", {"version": exported["version"], "data": {}})
    today = date.today()
    seeded = seed_ledger(api, today)
    api.post("/automatic-recordings/process-due")
    print(json.dumps({"client_id": args.client_id, **seeded}, ensure_ascii=False))


if __name__ == "__main__":
    main()
