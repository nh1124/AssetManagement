"""Compute the plan rows of 物品の取り置き (§8-4): earmarks whose amounts come from their products.

For each month of a range, every such earmark gets a row per funding account, from:
- the base (基準), the same every month of the range:
  saved: the earmark's saved monthly amount (取り置きに設定した月額);
  remaining: what fits the time left (残り期間に合わせる), each product's recommended monthly
  reserve as of the range's first month -- an asset's price over the months left to its
  replacement, a consumable's monthly cost;
- less what the earmark already holds (確保済みの額), taken off either
  recent: from the nearest months first (直近の月から), until it is used up, or
  even: the same amount every month (均一に) -- the held amount over the months to the
  latest replacement month (over the range's months when no product has one).
A month is not planned after the earmark's latest replacement month. The earmark's rows
in these months are replaced whatever wrote them; a month that needs nothing gets a ¥0
row, so the saved monthly amount does not stand in for it. Nothing changes until the user
confirms the exact preview: apply recomputes it and refuses when the fingerprint differs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from sqlalchemy.orm import Session

from .. import models
from ..domain.errors import Refused
from ..domain.money import Money
from .budget_lines import capsule_shares
from .budget_plan_store import active_lines_for_periods
from .capsule_service import claimed_value_minor
from .money_storage import money_client_currency, to_minor
from .product_reserve_service import _add_months, product_reserve_values, should_use_reserve

SOURCE = "product_reserve"
BASES = ("saved", "remaining")
HELD = ("recent", "even")
MAX_MONTHS = 24


def _index(period: str) -> int:
    year, month = (int(part) for part in period.split("-"))
    return year * 12 + month - 1


def _period(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _periods(start: str, end: str) -> list[str]:
    first, last = _index(start), _index(end)
    if last < first:
        raise Refused("終了月は開始月以降にしてください。", status_code=422)
    if last - first + 1 > MAX_MONTHS:
        raise Refused(f"一度に作れるのは{MAX_MONTHS}か月までです。", status_code=422)
    return [_period(index) for index in range(first, last + 1)]


def _earmarks(db: Session, client_id: int) -> dict[int, tuple[models.Capsule, list[models.Product]]]:
    """{capsule_id: (earmark, its products)}: the earmarks whose products reserve money."""
    found: dict[int, tuple[models.Capsule, list[models.Product]]] = {}
    products = db.query(models.Product).filter(
        models.Product.client_id == client_id, models.Product.funding_capsule_id.isnot(None),
    ).order_by(models.Product.id).all()
    for product in products:
        if not should_use_reserve(product):
            continue
        if product.funding_capsule_id not in found:
            capsule = db.query(models.Capsule).filter_by(id=product.funding_capsule_id, client_id=client_id).first()
            if capsule is None:
                continue
            found[capsule.id] = (capsule, [])
        found[product.funding_capsule_id][1].append(product)
    return found


def _replacement_index(product: models.Product) -> int | None:
    """The month an asset is replaced in; None for a consumable or an asset without a purchase date."""
    if not product.is_asset or not product.purchase_date or not product.lifespan_months:
        return None
    when = _add_months(product.purchase_date, product.lifespan_months)
    return when.year * 12 + when.month - 1


def schedule(base_minor: int, held_minor: int, months: int, horizon: int, held: str) -> list[int]:
    """The rows of `months` months: base each, less the held amount (recent: nearest first; even: held / horizon each)."""
    rows = []
    left = held_minor
    each = held_minor // max(1, horizon)
    for _ in range(months):
        if held == "recent":
            taken = min(base_minor, left)
            left -= taken
            rows.append(base_minor - taken)
        else:
            rows.append(max(0, base_minor - each))
    return rows


def plan(db: Session, client_id: int, start: str, end: str, plan_id: int | None, base: str, held: str) -> dict:
    if base not in BASES or held not in HELD:
        raise Refused("基準と確保済みの額の引き方を選んでください。", status_code=422)
    periods = _periods(start, end)
    first = _index(periods[0])
    currency = money_client_currency(db, client_id)
    names = {account.id: account.name for account in db.query(models.Account).filter_by(client_id=client_id).all()}
    earmarks = _earmarks(db, client_id)
    stored = [line for line in active_lines_for_periods(db, client_id, plan_id, periods)
              if line.line_type == "allocation" and line.target_type == "capsule" and line.target_id in earmarks]
    reference = date(first // 12, first % 12 + 1, 1)
    changes, warnings, summaries = [], [], []
    for capsule_id, (capsule, products) in sorted(earmarks.items()):
        if not capsule.funding_sources:
            warnings.append(f"取り置き「{capsule.name}」は資金元の口座がないため作りません。取り置きの画面で口座を設定してください。")
            continue
        if base == "saved":
            base_minor = capsule.monthly_contribution_minor or 0
        else:
            base_minor = sum(to_minor(product_reserve_values(product, reference, currency)["recommended_monthly_reserve"], currency)
                             for product in products)
        held_minor = max(0, claimed_value_minor(db, client_id, capsule_id))
        replaced = [index for index in (_replacement_index(product) for product in products) if index is not None]
        consumables = any(_replacement_index(product) is None for product in products)
        last = None if consumables or not replaced else max(replaced)
        # Months to the latest replacement (inclusive of the first month); the range's months without one.
        horizon = len(periods) if last is None else max(1, last - first)
        planned_months = [period for period in periods if last is None or _index(period) < last]
        rows = schedule(base_minor, held_minor, len(planned_months), horizon, held)
        summaries.append({"capsule_id": capsule_id, "name": capsule.name, "base": Money(base_minor, currency).to_float(),
                          "held": Money(held_minor, currency).to_float(),
                          "replacement": _period(last) if last is not None else None})
        wanted: dict[tuple[str, int | None], int] = {}
        for period, amount in zip(planned_months, rows):
            for account_id, part in capsule_shares(capsule, Money(amount, currency)):
                wanted[(period, account_id)] = part.minor
        virtual = {account_id: part.minor for account_id, part in capsule_shares(capsule, Money(capsule.monthly_contribution_minor or 0, currency))}
        mine = [line for line in stored if line.target_id == capsule_id]
        kept: dict[tuple[str, int | None], models.MonthlyPlanLine] = {}
        for line in sorted(mine, key=lambda row: row.id):
            key = (line.target_period, line.account_id)
            if key in wanted and key not in kept:
                kept[key] = line
                continue
            # A second row for the same month and account, an account-less legacy row, or a month after the replacement.
            changes.append(_change(capsule, line.target_period, line.account_id, names, line, line.amount_minor, 0, True, currency))
        for (period, account_id), new in sorted(wanted.items(), key=lambda item: (item[0][0], item[0][1] or 0)):
            line = kept.get((period, account_id))
            current = line.amount_minor if line is not None else virtual.get(account_id, 0)
            changes.append(_change(capsule, period, account_id, names, line, current, new, False, currency))
    basis = {"periods": periods, "base": base, "held": held,
             "changes": [{key: change[key] for key in ("period", "capsule_id", "account_id", "line_id", "current_minor", "new_minor", "retire")}
                         for change in changes]}
    fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
    return {"periods": periods, "currency": currency, "base": base, "held": held, "earmarks": summaries,
            "changes": changes, "warnings": warnings, "fingerprint": fingerprint}


def _change(capsule, period, account_id, names, line, current, new, retire, currency) -> dict:
    return {"period": period, "capsule_id": capsule.id, "capsule_name": capsule.name,
            "account_id": account_id, "account_name": names.get(account_id),
            "line_id": line.id if line is not None else None,
            "current": Money(current, currency).to_float(), "new": Money(new, currency).to_float(),
            "current_minor": current, "new_minor": new, "retire": retire,
            # A month without a row is always written: the row stands for the earmark's saved amount.
            "changed": retire or line is None or line.amount_minor != new}
