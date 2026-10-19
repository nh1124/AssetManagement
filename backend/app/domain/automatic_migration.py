"""Shared WP13 conversion for a migration snapshot and older backups."""
from __future__ import annotations

import calendar
from datetime import date

REMOVED_FIELDS = {
    "entry_type", "line_type", "category", "budget_treatment", "funding_capsule_id",
    "generate_recurring", "auto_post", "auto_depreciation", "source_product_id",
    "source_recurring_transaction_id", "start_period", "end_period",
}


def _date(value):
    return date.fromisoformat(str(value)[:10]) if value else None


def migrate_automatic_data(data: dict) -> dict[str, int]:
    recurring = {row["id"]: row for row in data.get("recurring_transactions", [])}
    original_entries = list(data.get("registry_entries", []))
    existing_ids = {row["id"] for row in original_entries}
    for row in original_entries:
        linked = recurring.get(row.get("source_recurring_transaction_id"))
        if linked is not None and not linked.get("source_registry_entry_id"):
            linked["source_registry_entry_id"] = row["id"]
    # Backups before registry ownership can contain only recurring rows. Preserve
    # those schedules too; a live database's FK already rules this case out.
    accounts = {row["id"]: row for row in data.get("accounts", [])}
    restored = 0
    next_id = max(existing_ids, default=0) + 1
    for linked in recurring.values():
        if linked.get("source_registry_entry_id") in existing_ids:
            continue
        kind = "income" if accounts.get(linked.get("from_account_id"), {}).get("account_type") == "income" else {"expense": "service", "liability": "debt"}.get(accounts.get(linked.get("to_account_id"), {}).get("account_type"), "allocation")
        original_entries.append({**linked, "id": next_id, "entry_type": kind, "generate_recurring": True,
                                 "source_account_id": linked.get("from_account_id"), "destination_account_id": linked.get("to_account_id"),
                                 "source_recurring_transaction_id": linked["id"]})
        linked["source_registry_entry_id"] = next_id
        next_id += 1
        restored += 1
    by_entry = {}
    for row in recurring.values():
        by_entry[row.get("source_registry_entry_id")] = row
    products = {row["id"]: row for row in data.get("products", [])}
    kept = []
    counts = {"product_rows_deleted": 0, "non_posting_disabled": 0, "irregular_disabled": 0, "manual_disabled": 0}
    for original in original_entries:
        row = dict(original)
        if "kind" in row:
            kept.append(row)
            continue
        product_id = row.get("source_product_id")
        if product_id is not None:
            if product_id in products:
                enabled = bool(row.get("auto_depreciation") and row.get("is_active", True))
                products[product_id]["auto_depreciation"] = bool(products[product_id].get("auto_depreciation") or enabled)
                if row.get("auto_depreciation") and not row.get("is_active", True):
                    counts["inactive_depreciation_disabled"] = counts.get("inactive_depreciation_disabled", 0) + 1
            counts["product_rows_deleted"] += 1
            continue
        linked = recurring.get(row.get("source_recurring_transaction_id")) or by_entry.get(row["id"])
        start = _date(row.get("start_period") + "-01") if row.get("start_period") else _date(row.get("created_at"))
        start = start or date(1970, 1, 1)
        end = _date(row.get("end_period") + "-01") if row.get("end_period") else None
        if end:
            end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
        non_posting = not row.get("generate_recurring", False)
        irregular = row.get("frequency") == "Irregular"
        manual = not row.get("auto_post", (linked or {}).get("auto_post", True)) or (linked is not None and (not linked.get("auto_post", True) or not linked.get("is_active", True)))
        counts["non_posting_disabled"] += int(non_posting)
        counts["irregular_disabled"] += int(irregular)
        counts["manual_disabled"] += int(manual)
        row.update(kind={"service": "expense", "income": "income", "debt": "debt", "allocation": "transfer"}.get(row.get("entry_type"), "expense"),
                   repeat_mode="indefinite", repeat_count=None, start_date=start.isoformat(), end_date=end.isoformat() if end else None,
                   next_due_date=(linked or {}).get("next_due_date"),
                   is_active=bool(row.get("is_active", True) and not non_posting and not irregular and not manual))
        if irregular:
            row["frequency"] = "Monthly"
            row["day_of_month"] = row.get("day_of_month") or start.day
        for field in REMOVED_FIELDS:
            row.pop(field, None)
        for field in ("from_account_id", "to_account_id", "source_registry_entry_id"):
            row.pop(field, None)
        kept.append(row)
    if restored:
        counts["orphan_recurring_restored"] = restored
    valid = {row["id"] for row in kept}
    for row in data.get("transactions", []):
        recurring_id = row.pop("recurring_transaction_id", None)
        if recurring_id is not None:
            entry_id = recurring.get(recurring_id, {}).get("source_registry_entry_id")
            row["registry_entry_id"] = entry_id if entry_id in valid else None
    data["registry_entries"] = kept
    migrate_automatic_operations(data, list(recurring.values()))
    data.pop("recurring_transactions", None)
    for row in products.values():
        row.setdefault("auto_depreciation", False)
    return counts


def migrate_automatic_operations(data: dict, old_recurring: list[dict]) -> None:
    """Keep saved actions usable and require renewed approval when posting semantics change."""
    import hashlib
    import json
    from .money import Money
    by_id = {row['id']: row for row in old_recurring}
    entries = {row['id']: row for row in data.get('registry_entries', [])}
    accounts = {row['id']: row for row in data.get('accounts', [])}

    def payload(old: dict, base: dict | None = None, start: str | None = None) -> dict:
        source = {**(base or {}), **old}
        src = old.get('source_account_id', old.get('from_account_id', (base or {}).get('source_account_id')))
        dst = old.get('destination_account_id', old.get('to_account_id', (base or {}).get('destination_account_id')))
        kind = 'income' if accounts.get(src, {}).get('account_type') == 'income' else {'expense': 'expense', 'liability': 'debt'}.get(accounts.get(dst, {}).get('account_type'), 'transfer')
        currency = source.get('currency') or 'JPY'
        amount = source.get('amount')
        if amount is None and source.get('amount_minor') is not None:
            amount = Money(source['amount_minor'], currency).to_float()
        first = old.get('start_date') or ((old['start_period'] + '-01') if old.get('start_period') else source.get('start_date') or start or str(source.get('created_at') or '1970-01-01')[:10])
        end = old.get('end_date', (base or {}).get('end_date'))
        if old.get('end_period'):
            end = _date(source['end_period'] + '-01')
            end = end.replace(day=calendar.monthrange(end.year, end.month)[1]).isoformat()
        return {'name': source.get('name', ''), 'amount': amount or 0, 'currency': currency, 'kind': old.get('kind') or (kind if 'from_account_id' in old or 'to_account_id' in old else source.get('kind') or kind),
                'source_account_id': src, 'destination_account_id': dst, 'budget_account_id': source.get('budget_account_id'),
                'repeat_mode': source.get('repeat_mode', 'indefinite'), 'frequency': source.get('frequency', 'Monthly'),
                'frequency_days': source.get('frequency_days'), 'day_of_month': source.get('day_of_month') or 1,
                'month_of_year': source.get('month_of_year'), 'start_date': first, 'end_date': end, 'repeat_count': source.get('repeat_count'),
                'is_active': bool(source.get('is_active', True) and source.get('auto_post', True)),
                'budget_active': source.get('budget_active', True), 'note': source.get('note')}

    def references(value):
        if isinstance(value, list):
            return [references(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in {'recurring_id', 'recurring_transaction_id', 'source_recurring_transaction_id'}:
                entry_id = by_id.get(item, {}).get('source_registry_entry_id')
                result['registry_entry_id'] = entry_id if entry_id in entries else None
            elif key == 'source_registry_entry_id':
                result['registry_entry_id'] = item if item in entries else None
            else:
                result[key] = references(item)
        return result

    for row in data.get('monthly_actions', []):
        old_kind = row['kind']
        if old_kind == 'add_recurring':
            row['kind'] = 'add_auto_transaction'
            row['payload'] = payload(row.get('payload') or {}, start=(row.get('target_period') or row['source_period']) + '-01')
        elif old_kind == 'pause_recurring':
            row['kind'] = 'stop_auto_transaction'
            row['payload'] = references(row.get('payload') or {})
            row['target_id'] = row['payload'].get('registry_entry_id')
        row['result'] = references(row.get('result') or {})
    for row in data.get('ai_change_requests', []):
        if row['resource'] != 'recurring_transactions' or row['status'] not in {'draft', 'pending', 'approved'}:
            continue
        recurring_id = (row.get('target_ref') or {}).get('id')
        base = entries.get(by_id.get(recurring_id, {}).get('source_registry_entry_id'))
        row['resource'] = 'auto_transactions'
        row['target_ref'] = {'id': base['id']} if base else {}
        row['input_payload'] = payload(row.get('input_payload') or {}, base)
        if row['status'] in {'draft', 'pending', 'approved'}:
            row['status'] = 'pending'
            row['approved_by_client_id'] = row['approved_at'] = None
        before = {**payload({}, base), 'id': base['id'], 'next_due_date': base.get('next_due_date')} if base else {}
        row['before_snapshot'] = before
        row['after_snapshot'] = {**before, **row['input_payload'], 'id': base['id'] if base else None}
        row['diff'] = {'changes': [{'field': key, 'before': before.get(key), 'after': value} for key, value in row['after_snapshot'].items() if before.get(key) != value]}
        row['diff']['count'] = len(row['diff']['changes'])
        row['precondition_hash'] = hashlib.sha256(json.dumps(before, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()
        row['result'] = references(row.get('result') or {})
