"""Pure backup format rules; existing exports must keep verifying."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Any

EXPORT_VERSION = 11

DATA_COLLECTIONS = [
    "accounts",
    "products",
    "simulation_configs",
    "recurring_transactions",
    "registry_entries",
    "quick_templates",
    "transaction_batches",
    "life_events",
    "transactions",
    "journal_entries",
    "budget_plans",
    "monthly_plan_lines",
    "period_reviews",
    "monthly_actions",
    "milestones",
    "capsules",
    "capsule_funding_sources",
    "capsule_rules",
    "simulation_scenarios",
    "exchange_rates",
]


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def row_fields(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {field: _iso(getattr(obj, field)) for field in fields}


def _normalize_for_checksum(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_for_checksum(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_for_checksum(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _canonical_json(value: Any) -> str:
    normalized = _normalize_for_checksum(value)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def data_counts(data: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {key: len(data.get(key, [])) for key in DATA_COLLECTIONS}


def _table_checksums(data: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    return {key: _sha256(data.get(key, [])) for key in DATA_COLLECTIONS}


def build_manifest(
    client_id: int,
    data: dict[str, list[dict[str, Any]]],
    exported_at: str,
    alembic_revision: str | None,
) -> dict[str, Any]:
    checksums = _table_checksums(data)
    return {
        "export_version": EXPORT_VERSION,
        "exported_at": exported_at,
        "application": "AssetManagement",
        "alembic_revision": alembic_revision,
        "client_id": client_id,
        "counts": data_counts(data),
        "checksums": checksums,
        "payload_checksum": _sha256({"data": data, "checksums": checksums}),
    }


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_import_payload(
    data: dict[str, list[dict[str, Any]]],
    version: int | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = data or {}
    issues: list[dict[str, Any]] = []

    def issue(
        severity: str,
        code: str,
        detail: str,
        collection: str | None = None,
        item_id: Any = None,
        field: str | None = None,
    ) -> None:
        row = {"severity": severity, "code": code, "detail": detail}
        if collection:
            row["collection"] = collection
        if item_id is not None:
            row["item_id"] = item_id
        if field:
            row["field"] = field
        issues.append(row)

    unknown_collections = sorted(set(data.keys()) - set(DATA_COLLECTIONS))
    for collection in unknown_collections:
        issue("warning", "unknown_collection", "This collection is not imported by this application version.", collection)

    if version and version > EXPORT_VERSION:
        issue(
            "error",
            "unsupported_version",
            f"Export version {version} is newer than supported version {EXPORT_VERSION}.",
        )
    elif version and version < EXPORT_VERSION:
        issue(
            "warning",
            "older_version",
            f"Export version {version} will be imported with compatibility defaults.",
        )

    id_sets: dict[str, set[int]] = {}
    for collection in DATA_COLLECTIONS:
        seen: set[int] = set()
        for index, item in enumerate(data.get(collection, [])):
            item_id = _as_int(item.get("id"))
            if item_id is None:
                issue("error", "missing_id", f"Row {index} is missing a valid id.", collection, field="id")
                continue
            if item_id in seen:
                issue("error", "duplicate_id", f"Duplicate id {item_id}.", collection, item_id, "id")
            seen.add(item_id)
        id_sets[collection] = seen

    def check_ref(collection: str, field: str, target: str, required: bool = False) -> None:
        target_ids = id_sets.get(target, set())
        for item in data.get(collection, []):
            value = item.get(field)
            ref_id = _as_int(value)
            if ref_id is None:
                if required and value is not None:
                    issue("error", "invalid_reference", f"{field} is not a valid integer id.", collection, item.get("id"), field)
                elif required:
                    issue("error", "missing_reference", f"{field} is required.", collection, item.get("id"), field)
                continue
            if ref_id not in target_ids:
                issue(
                    "error",
                    "missing_reference",
                    f"{field} points to missing {target} id {ref_id}.",
                    collection,
                    item.get("id"),
                    field,
                )

    check_ref("accounts", "parent_id", "accounts")
    check_ref("products", "budget_account_id", "accounts")
    check_ref("products", "funding_capsule_id", "capsules")
    check_ref("recurring_transactions", "from_account_id", "accounts")
    check_ref("recurring_transactions", "to_account_id", "accounts")
    # Definitions without a restorable registry owner are skipped during import.
    check_ref("registry_entries", "budget_account_id", "accounts")
    check_ref("registry_entries", "source_account_id", "accounts")
    check_ref("registry_entries", "destination_account_id", "accounts")
    check_ref("registry_entries", "funding_capsule_id", "capsules")
    check_ref("registry_entries", "source_product_id", "products")
    check_ref("registry_entries", "source_recurring_transaction_id", "recurring_transactions")
    check_ref("quick_templates", "default_from_account_id", "accounts")
    check_ref("quick_templates", "default_to_account_id", "accounts")
    check_ref("transaction_batches", "quick_template_id", "quick_templates")
    # Only present in a v6 or older payload, where the columns still existed.
    check_ref("transactions", "from_account_id", "accounts")
    check_ref("transactions", "to_account_id", "accounts")
    check_ref("transactions", "batch_id", "transaction_batches")
    check_ref("journal_entries", "transaction_id", "transactions", required=True)
    check_ref("journal_entries", "account_id", "accounts", required=True)
    check_ref("journal_entries", "capsule_id", "capsules")
    check_ref("milestones", "life_event_id", "life_events")
    check_ref("capsules", "life_event_id", "life_events")
    check_ref("capsule_funding_sources", "capsule_id", "capsules", required=True)
    check_ref("capsule_funding_sources", "account_id", "accounts", required=True)
    check_ref("capsule_rules", "capsule_id", "capsules", required=True)
    check_ref("capsule_rules", "source_account_id", "accounts")
    check_ref("simulation_scenarios", "life_event_id", "life_events", required=True)
    check_ref("monthly_plan_lines", "account_id", "accounts")
    check_ref("monthly_plan_lines", "source_account_id", "accounts")
    check_ref("monthly_plan_lines", "plan_id", "budget_plans")

    journal_entries_by_transaction: dict[int, list[dict[str, Any]]] = {}
    for entry in data.get("journal_entries", []):
        transaction_id = _as_int(entry.get("transaction_id"))
        if transaction_id is not None:
            journal_entries_by_transaction.setdefault(transaction_id, []).append(entry)

    for transaction in data.get("transactions", []):
        transaction_id = _as_int(transaction.get("id"))
        if transaction_id is None:
            continue
        entries = journal_entries_by_transaction.get(transaction_id, [])
        if len(entries) < 2:
            issue(
                "error",
                "journal_entries_missing",
                "Each transaction must have at least two journal entries.",
                "transactions",
                transaction_id,
            )
            continue
        try:
            amount = float(transaction.get("amount") or 0.0)
            total_debit = sum(float(entry.get("debit") or 0.0) for entry in entries)
            total_credit = sum(float(entry.get("credit") or 0.0) for entry in entries)
        except (TypeError, ValueError):
            issue(
                "error",
                "journal_amount_invalid",
                "Transaction and journal amounts must be numeric.",
                "transactions",
                transaction_id,
            )
            continue
        if not (
            math.isclose(total_debit, total_credit, abs_tol=0.01)
            and math.isclose(total_debit, amount, abs_tol=0.01)
        ):
            issue(
                "error",
                "journal_unbalanced",
                f"Journal totals must satisfy debit=credit=amount; got debit={total_debit}, credit={total_credit}, amount={amount}.",
                "transactions",
                transaction_id,
            )

    for item in data.get("monthly_plan_lines", []):
        target_type = item.get("target_type")
        target_id = _as_int(item.get("target_id"))
        if target_id is None:
            continue
        target_collection = {
            "account": "accounts",
            "capsule": "capsules",
            "life_event": "life_events",
            "product": "products",
        }.get(target_type)
        if target_collection and target_id not in id_sets[target_collection]:
            issue(
                "error",
                "missing_reference",
                f"target_id points to missing {target_collection} id {target_id}.",
                "monthly_plan_lines",
                item.get("id"),
                "target_id",
            )

    manifest = manifest or {}
    expected_counts = manifest.get("counts") or {}
    actual_counts = data_counts(data)
    for collection, expected in expected_counts.items():
        actual = actual_counts.get(collection)
        if actual is not None and expected != actual:
            issue(
                "error",
                "count_mismatch",
                f"Manifest count {expected} does not match payload count {actual}.",
                collection,
            )

    expected_checksums = manifest.get("checksums") or {}
    actual_checksums = _table_checksums(data)
    for collection, expected in expected_checksums.items():
        actual = actual_checksums.get(collection)
        if actual and expected != actual:
            issue(
                "warning",
                "checksum_mismatch",
                "Collection checksum does not match the export manifest. This can happen with older exports after JSON number normalization.",
                collection,
            )

    expected_payload_checksum = manifest.get("payload_checksum")
    if expected_payload_checksum:
        actual_payload_checksum = _sha256({"data": data, "checksums": actual_checksums})
        if expected_payload_checksum != actual_payload_checksum:
            issue(
                "warning",
                "payload_checksum_mismatch",
                "Payload checksum does not match the export manifest. This can happen with older exports after JSON number normalization.",
            )

    error_count = sum(1 for item in issues if item["severity"] == "error")
    warning_count = sum(1 for item in issues if item["severity"] == "warning")
    return {
        "status": "valid" if error_count == 0 else "invalid",
        "error_count": error_count,
        "warning_count": warning_count,
        "counts": data_counts(data),
        "issues": issues,
    }


def assert_imported_journal_invariant(
    transaction_id: int,
    amount: Any,
    entries: list[dict[str, Any]],
) -> None:
    if len(entries) < 2:
        raise ValueError(f"Transaction {transaction_id} has fewer than two journal entries")
    total_debit = sum(float(entry.get("debit") or 0.0) for entry in entries)
    total_credit = sum(float(entry.get("credit") or 0.0) for entry in entries)
    amount = float(amount or 0.0)
    if not (
        math.isclose(total_debit, total_credit, abs_tol=0.01)
        and math.isclose(total_debit, amount, abs_tol=0.01)
    ):
        raise ValueError(
            f"Transaction {transaction_id} journal totals do not satisfy debit=credit=amount"
        )


def remap_nested_ids(value: Any, key_maps: dict[str, dict[int, int]]) -> Any:
    if isinstance(value, list):
        return [remap_nested_ids(item, key_maps) for item in value]
    if not isinstance(value, dict):
        return value

    mapped: dict[str, Any] = {}
    for key, item_value in value.items():
        id_map = key_maps.get(key)
        old_id = _as_int(item_value)
        if id_map is not None and old_id is not None:
            mapped[key] = id_map.get(old_id, item_value)
        else:
            mapped[key] = remap_nested_ids(item_value, key_maps)
    return mapped


def remap_action_target_id(item: dict[str, Any], key_maps: dict[str, dict[int, int]]) -> int | None:
    target_id = _as_int(item.get("target_id"))
    if target_id is None:
        return None
    kind = item.get("kind")
    payload = item.get("payload") or {}
    target_key = {
        "set_budget": "account_id",
        "pause_recurring": "recurring_id",
        "change_capsule_contribution": "capsule_id",
    }.get(kind)
    if kind == "boost_allocation":
        target_key = "account_id" if payload.get("account_id") else "life_event_id"
    if not target_key:
        return target_id
    return key_maps.get(target_key, {}).get(target_id, target_id)
