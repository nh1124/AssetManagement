"""Pure backup format rules; existing exports must keep verifying."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any

EXPORT_VERSION = 28

DATA_COLLECTIONS = [
    "accounts",
    "products",
    "product_depreciations",
    "simulation_configs",
    "registry_entries",
    "transaction_batches",
    "life_events",
    "life_event_fundings",
    "life_event_links",
    "life_scenarios",
    "scenario_contribution_plans",
    "household_members",
    "life_event_conditions",
    "transactions",
    "journal_entries",
    "budget_plans",
    "monthly_plan_lines",
    "period_reviews",
    "period_closes",
    "monthly_actions",
    "capsules",
    "capsule_drawdowns",
    "capsule_funding_sources",
    "capsule_rules",
    "fx_tracked_currencies",
    "exchange_rates",
    "goal_budget_reflections",
]

# Collections a later version stopped keeping, with the export version that
# dropped them. Older exports still carry them: their manifest checksums still
# verify, but the rows are never imported.
RETIRED_COLLECTIONS = {"recurring_transactions": 24, "life_scenario_choices": 22, "quick_templates": None,
                       "life_scenario_account_returns": 26, "milestones": 26, "simulation_scenarios": 26, "goal_baselines": 26,
                       "goal_event_earmarks": 27}


def _retired(version: int | None) -> set[str]:
    # None: retired without a version bump, so every export may carry it.
    return {
        name for name, dropped_in in RETIRED_COLLECTIONS.items()
        if dropped_in is None or version is None or version < dropped_in
    }


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

    legacy = version is None or version < 22
    retired = _retired(version)
    unknown_collections = sorted(set(data.keys()) - set(DATA_COLLECTIONS) - retired)
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
        if collection == "fx_tracked_currencies":
            continue
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

    for item in data.get("accounts", []):
        if "account_type" in item and item["account_type"] not in {"asset", "liability", "income", "expense"}:
            issue("error", "invalid_account_type", "口座の種類が不正です。", "accounts", item.get("id"), "account_type")

    seen_currencies = set()
    for item in data.get("fx_tracked_currencies", []):
        currency = item.get("currency")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency) or currency in seen_currencies:
            issue("error", "invalid_tracked_currency", "追跡通貨が不正または重複しています。", "fx_tracked_currencies")
        if isinstance(currency, str):
            seen_currencies.add(currency)

    check_ref("products", "budget_account_id", "accounts")
    check_ref("products", "funding_capsule_id", "capsules")
    # Definitions without a restorable registry owner are skipped during import.
    check_ref("registry_entries", "budget_account_id", "accounts")
    check_ref("registry_entries", "source_account_id", "accounts")
    check_ref("registry_entries", "destination_account_id", "accounts")
    if version and version >= 24:
        check_ref("transactions", "registry_entry_id", "registry_entries")
    # Only present in a v6 or older payload, where the columns still existed.
    check_ref("transactions", "from_account_id", "accounts")
    check_ref("transactions", "to_account_id", "accounts")
    check_ref("transactions", "batch_id", "transaction_batches")
    check_ref("journal_entries", "transaction_id", "transactions", required=True)
    check_ref("journal_entries", "account_id", "accounts", required=True)
    check_ref("journal_entries", "capsule_id", "capsules")
    check_ref("life_event_conditions", "life_event_id", "life_events", required=True)
    # Only present before v28, when an event named one account itself.
    check_ref("life_events", "account_id", "accounts", required=False)
    check_ref("life_event_fundings", "life_event_id", "life_events", required=True)
    check_ref("life_event_fundings", "account_id", "accounts", required=True)
    check_ref("life_event_links", "from_event_id", "life_events", required=True)
    check_ref("life_event_links", "to_event_id", "life_events", required=True)
    if not legacy:
        check_ref("life_events", "scenario_id", "life_scenarios", required=True)
    check_ref("life_scenario_account_returns", "scenario_id", "life_scenarios", required=True)
    check_ref("life_scenario_account_returns", "account_id", "accounts", required=True)
    check_ref("capsule_funding_sources", "capsule_id", "capsules", required=True)
    check_ref("capsule_funding_sources", "account_id", "accounts", required=True)
    check_ref("capsule_drawdowns", "capsule_id", "capsules", required=True)
    check_ref("capsule_drawdowns", "transaction_id", "transactions", required=True)
    check_ref("capsule_rules", "capsule_id", "capsules", required=True)
    check_ref("capsule_rules", "source_account_id", "accounts")
    check_ref("capsule_rules", "trigger_account_id", "accounts")
    check_ref("scenario_contribution_plans", "scenario_id", "life_scenarios", required=True)
    check_ref("scenario_contribution_plans", "account_id", "accounts", required=True)
    check_ref("capsules", "goal_event_id", "life_events")
    check_ref("life_events", "borrowing_event_id", "life_events")
    check_ref("monthly_plan_lines", "account_id", "accounts")
    check_ref("monthly_plan_lines", "source_account_id", "accounts")
    check_ref("monthly_plan_lines", "plan_id", "budget_plans")

    scenario_names, goal_count = set(), 0
    for item in data.get("life_scenarios", []):
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or name != name.strip() or name in scenario_names:
            issue("error", "invalid_scenario_name", "シナリオ名は空白を除いた重複のない名前にしてください。", "life_scenarios", item.get("id"))
        if isinstance(name, str):
            scenario_names.add(name)
        if type(item.get("is_goal", False)) is not bool:
            issue("error", "invalid_scenario_goal", "ゴールの指定が不正です。", "life_scenarios", item.get("id"))
        goal_count += item.get("is_goal") is True
        horizon = item.get("horizon_years", 30)
        if type(horizon) is not int or not 1 <= horizon <= 60:
            issue("error", "invalid_horizon_years", "試算期間は1〜60年で指定してください。", "life_scenarios", item.get("id"))
    if goal_count > 1:
        issue("error", "multiple_scenario_goals", "ゴールのシナリオは1つだけ指定してください。", "life_scenarios")
    for collection, fields in (("life_scenarios", ("annual_return", "inflation")), ("life_scenario_account_returns", ("annual_return",))):
        for item in data.get(collection, []):
            for field in fields:
                default = {"annual_return": 5.0, "inflation": 2.0}[field] if collection == "life_scenarios" else None
                value = item.get(field, default)
                if type(value) not in (int, float) or not math.isfinite(value):
                    issue("error", "invalid_scenario_rate", "利率は有限の数値で指定してください。", collection, item.get("id"), field)
    plan_keys = set()
    for item in data.get("scenario_contribution_plans", []):
        key = (_as_int(item.get("scenario_id")), _as_int(item.get("account_id")), item.get("start_period"))
        amount, rate = item.get("monthly_amount_minor"), item.get("annual_return")
        valid = isinstance(key[2], str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", key[2]) is not None and key not in plan_keys
        valid = valid and type(amount) is int and (rate is None or (type(rate) in (int, float) and math.isfinite(rate)))
        if not valid:
            issue("error", "invalid_contribution_plan", "積立設定のレコードが不正または重複しています。", "scenario_contribution_plans", item.get("id"))
        plan_keys.add(key)
    pairs = set()
    accounts_by_id = {_as_int(row.get("id")): row for row in data.get("accounts", [])}
    for item in data.get("life_scenario_account_returns", []):
        pair = (_as_int(item.get("scenario_id")), _as_int(item.get("account_id")))
        if accounts_by_id.get(pair[1], {}).get("account_type") != "asset" or pair in pairs:
            issue("error", "invalid_scenario_account", "資産口座を重複なく選択してください。", "life_scenario_account_returns", item.get("id"))
        pairs.add(pair)

    events_by_id = {_as_int(row.get("id")): row for row in data.get("life_events", [])}
    if not legacy:
        from uuid import UUID
        lineages = set()
        for item in data.get("life_events", []):
            lineage = item.get("lineage")
            pair = (_as_int(item.get("scenario_id")), lineage)
            try:
                valid = isinstance(lineage, str) and len(lineage) == 36 and str(UUID(lineage)) == lineage
            except (ValueError, TypeError):
                valid = False
            if not valid or pair in lineages:
                issue("error", "invalid_event_lineage", "イベントの系統はシナリオ内で重複しないUUIDで指定してください。", "life_events", item.get("id"), "lineage")
            if valid:
                lineages.add(pair)

    link_pairs = set()
    graph: dict[int, list[int]] = {}
    for item in data.get("simulation_configs", []):
        horizon = item.get("horizon_years", 30)
        if type(horizon) is not int or not 1 <= horizon <= 60:
            issue("error", "invalid_horizon_years", "試算期間は1〜60年で指定してください。", "simulation_configs", item.get("id"))
    for item in data.get("life_events", []):
        if item.get("direction", "expense") not in {"expense", "income", "borrowing", "repayment"}:
            issue("error", "invalid_direction", "イベントの種別は expense・income・borrowing・repayment のいずれかです。", "life_events", item.get("id"))
        if item.get("condition_mode", "all") not in {"all", "any"}:
            issue("error", "invalid_condition_mode", "Condition mode must be all or any.", "life_events", item.get("id"))
    funding_pairs: set[tuple] = set()
    funding_totals: dict[int | None, int] = {}
    asset_ids = {_as_int(row.get("id")) for row in data.get("accounts", []) if row.get("account_type") == "asset"}
    for item in data.get("life_event_fundings", []):
        pair = (_as_int(item.get("life_event_id")), _as_int(item.get("account_id")))
        share = item.get("share_bp")
        if type(share) is not int or not 0 < share <= 10000 or pair in funding_pairs or pair[1] not in asset_ids:
            issue("error", "invalid_event_funding", "資金の割り当ては資産口座ごとに 1 件、割合は 0 より大きく 100% 以下にしてください。", "life_event_fundings", item.get("id"))
        funding_pairs.add(pair)
        funding_totals[pair[0]] = funding_totals.get(pair[0], 0) + (share if type(share) is int else 0)
    for event_id, total in funding_totals.items():
        if total > 10000:
            issue("error", "invalid_event_funding_total", "1 つのイベントの資金の割り当ては合計 100% 以下にしてください。", "life_event_fundings", event_id)
    reference_collections = {"account_balance": "accounts", "capsule_claim": "capsules", "goal_progress": "life_events", "member_age": "household_members"}
    for item in data.get("life_event_conditions", []):
        metric = item.get("metric")
        money = metric in {"net_worth", "free_cash", "account_balance", "capsule_claim"}
        numeric = metric in {"member_age", "goal_progress"}
        valid = metric in {*reference_collections, "net_worth", "free_cash", "date_reached"} and item.get("comparator") in {"gte", "lte", "eq"}
        valid = valid and (item.get("threshold_minor") is not None) == money and (item.get("threshold_number") is not None) == numeric and (item.get("threshold_date") is not None) == (metric == "date_reached")
        minor, number = item.get("threshold_minor"), item.get("threshold_number")
        if money:
            valid = valid and type(minor) is int and -(2**63) <= minor < 2**63
        if numeric:
            valid = valid and type(number) in {int, float} and math.isfinite(number)
        if metric == "date_reached":
            try:
                valid = valid and parse_date(item.get("threshold_date")) is not None
            except (TypeError, ValueError):
                valid = False
        reference = item.get("reference_id")
        # Null is also a dangling reference after restore; it must remain reportable.
        if reference is not None:
            valid = valid and metric in reference_collections and type(reference) is int and reference > 0
        if not valid:
            issue("error", "invalid_event_condition", "Condition metric, comparison or threshold is invalid.", "life_event_conditions", item.get("id"))

    indegree: dict[int, int] = dict.fromkeys(id_sets.get("life_events", set()), 0)
    for item in data.get("life_event_links", []):
        source, target = _as_int(item.get("from_event_id")), _as_int(item.get("to_event_id"))
        pair = (source, target)
        if source == target or pair in link_pairs:
            issue("error", "invalid_event_link", "Event links must be distinct non-self pairs.", "life_event_links", item.get("id"))
        link_pairs.add(pair)
        if item.get("kind") not in ({"after", "alternative"} if legacy else {"after"}) or type(item.get("offset_months", 0)) is not int:
            issue("error", "invalid_event_link", "Event links require a valid kind and integer month offset.", "life_event_links", item.get("id"))
        if type(item.get("adopted", False)) is not bool:
            issue("error", "invalid_event_link", "Event link adoption must be a boolean.", "life_event_links", item.get("id"))
        if not legacy and events_by_id.get(source, {}).get("scenario_id") != events_by_id.get(target, {}).get("scenario_id"):
            issue("error", "cross_scenario_link", "同じシナリオのイベントを選択してください。", "life_event_links", item.get("id"))
        if source in indegree and target in indegree:
            graph.setdefault(source, []).append(target)
            indegree[target] += 1
    ready = [event_id for event_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        source = ready.pop()
        visited += 1
        for target in graph.get(source, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if visited != len(indegree):
        issue("error", "event_link_cycle", "Event links must not contain a cycle.", "life_event_links")

    closed_periods = set()
    for item in data.get("period_closes", []):
        period = item.get("period")
        valid_period = isinstance(period, str) and re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", period) and period[:4] != "0000"
        if not valid_period:
            issue("error", "invalid_period", "Period must be a valid YYYY-MM.", "period_closes", item.get("id"), "period")
        elif period in closed_periods:
            issue("error", "duplicate_period_close", "A month can be closed only once.", "period_closes", item.get("id"), "period")
        if isinstance(period, str):
            closed_periods.add(period)
        try:
            closed_at = parse_datetime(item.get("closed_at"))
            if closed_at is None or closed_at.tzinfo is not None:
                raise ValueError("closed_at must be a naive UTC timestamp")
        except (TypeError, ValueError):
            issue("error", "invalid_closed_at", "closed_at must be a UTC timestamp without an offset.", "period_closes", item.get("id"), "closed_at")

    drawdown_pairs = set()
    for item in data.get("capsule_drawdowns", []):
        pair = (_as_int(item.get("capsule_id")), _as_int(item.get("transaction_id")))
        if pair in drawdown_pairs:
            issue("error", "duplicate_drawdown", "A transaction can have only one drawdown per capsule.",
                  "capsule_drawdowns", item.get("id"))
        drawdown_pairs.add(pair)
        if item.get("kind") not in {"as_intended", "diverted"}:
            issue("error", "invalid_drawdown_kind", "Drawdown kind must be as_intended or diverted.",
                  "capsule_drawdowns", item.get("id"), "kind")
        amount = item.get("amount_minor")
        if type(amount) is not int or amount <= 0:
            issue("error", "invalid_drawdown_amount", "Drawdown amount_minor must be a positive integer.",
                  "capsule_drawdowns", item.get("id"), "amount_minor")

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
    for collection in retired & set(expected_checksums):
        actual_checksums[collection] = _sha256(data.get(collection, []))
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
        # An older export predates later collections; its checksum covers only its own.
        covered = {key: value for key, value in actual_checksums.items() if key in expected_checksums} if expected_checksums else actual_checksums
        actual_payload_checksum = _sha256({"data": data, "checksums": covered})
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
    target_key = {
        "set_budget": "account_id",
        "stop_auto_transaction": "registry_entry_id",
        "change_capsule_contribution": "capsule_id",
    }.get(kind)
    if not target_key:
        return target_id
    return key_maps.get(target_key, {}).get(target_id, target_id)


def migrate_account_fields(data: dict, base_currency: str) -> dict:
    """Upgrade a verified pre-WP12 payload without changing its checksum input."""
    from copy import deepcopy
    result = deepcopy(data)
    returns = result.setdefault("life_scenario_account_returns", [])
    existing = {(int(row["scenario_id"]), int(row["account_id"])) for row in returns}
    next_id = max((row["id"] for row in returns), default=0) + 1
    for account in result.get("accounts", []):
        rate = account.get("expected_return")
        if account["account_type"] == "asset" and rate is not None:
            for scenario in result.get("life_scenarios", []):
                key = int(scenario["id"]), int(account["id"])
                if key not in existing:
                    returns.append({"id": next_id, "scenario_id": key[0], "account_id": key[1], "annual_return": rate})
                    next_id += 1
                    existing.add(key)
        for field in ("role", "role_target_amount", "role_target_amount_minor", "institution", "withdrawable_from_age", "parent_id", "expected_return"):
            account.pop(field, None)
    currencies = {code.strip().upper() for row in result.get("exchange_rates", []) for code in (row["base_currency"], row["quote_currency"])}
    result["fx_tracked_currencies"] = [{"currency": code} for code in sorted(currencies - {base_currency})]
    return result


LIFE_EVENT_RETIRED_FIELDS = ("start_date", "active_plan_basis", "active_plan_label", "plan_status_override", "budget_reflection", "archived_at")


def migrate_goal_fields(data: dict, period: str) -> dict:
    """Upgrade a verified pre-v26 payload the way migration 20261019_0078 upgrades the database.

    Scenario account yields become 積立設定 records from this month with no amount,
    an event's capsule becomes a full-share goal earmark, a plan row typed as the
    event moves to that capsule (or retires), and archived events are dropped with
    their links and conditions.
    """
    from copy import deepcopy
    result = deepcopy(data)
    archived = {_as_int(row.get("id")) for row in result.get("life_events", []) if row.get("archived_at")}
    result["life_events"] = [row for row in result.get("life_events", []) if _as_int(row.get("id")) not in archived]
    for row in result["life_events"]:
        for field in LIFE_EVENT_RETIRED_FIELDS:
            row.pop(field, None)
    result["life_event_links"] = [row for row in result.get("life_event_links", [])
                                  if not {_as_int(row.get("from_event_id")), _as_int(row.get("to_event_id"))} & archived]
    result["life_event_conditions"] = [row for row in result.get("life_event_conditions", [])
                                       if _as_int(row.get("life_event_id")) not in archived]
    result["scenario_contribution_plans"] = [
        {"id": index, "scenario_id": row["scenario_id"], "account_id": row["account_id"], "start_period": period,
         "monthly_amount_minor": 0, "annual_return": row["annual_return"], "note": None}
        for index, row in enumerate(result.get("life_scenario_account_returns", []), 1)
    ]
    capsule_by_event: dict[int, int] = {}
    earmarks = []
    for capsule in result.get("capsules", []):
        event_id = _as_int(capsule.pop("life_event_id", None))
        if capsule.get("capsule_type") == "life_event":
            capsule["capsule_type"] = "manual"
        if capsule.get("target_amount_source") == "life_event":
            capsule["target_amount_source"] = "manual"
        if event_id is not None and event_id not in archived:
            capsule_by_event.setdefault(event_id, _as_int(capsule["id"]))
            earmarks.append({"id": len(earmarks) + 1, "life_event_id": event_id, "capsule_id": capsule["id"], "share_bp": 10000})
    result["goal_event_earmarks"] = earmarks
    for line in result.get("monthly_plan_lines", []):
        if line.get("target_type") == "life_event":
            capsule_id = capsule_by_event.get(_as_int(line.get("target_id")))
            if capsule_id is None:
                line["is_active"] = False
            else:
                line["target_type"], line["target_id"] = "capsule", capsule_id
    for row in result.get("life_scenarios", []):
        row.pop("monthly_savings", None)
    for row in result.get("simulation_configs", []):
        row.pop("monthly_savings", None)
    for row in result.get("goal_budget_reflections", []):
        row.pop("options", None)
        row.pop("events", None)
    for collection in ("life_scenario_account_returns", "milestones", "simulation_scenarios", "goal_baselines"):
        result.pop(collection, None)
    return result


def migrate_goal_v2(data: dict) -> dict:
    """Upgrade a verified pre-v27 payload the way migration 20261019_0079 upgrades the database.

    An earmark linked to goal events (実績管理の設定) becomes the earmark made for its first
    linked event; an event's account that is not an asset account is dropped.
    """
    from copy import deepcopy
    result = deepcopy(data)
    first: dict[int, int] = {}
    for link in sorted(result.pop("goal_event_earmarks", []), key=lambda row: _as_int(row.get("id")) or 0):
        if (link.get("share_bp") or 0) > 0:
            first.setdefault(_as_int(link.get("capsule_id")), _as_int(link.get("life_event_id")))
    for capsule in result.get("capsules", []):
        capsule["goal_event_id"] = first.get(_as_int(capsule.get("id")))
    assets = {_as_int(row.get("id")) for row in result.get("accounts", []) if row.get("account_type") == "asset"}
    for event in result.get("life_events", []):
        if _as_int(event.get("account_id")) not in assets:
            event["account_id"] = None
    return result


def migrate_event_fundings(data: dict) -> dict:
    """Upgrade a verified pre-v28 payload the way migration 20261020_0081 upgrades the database.

    An event's own asset account becomes its 資金の割り当て for the whole event.
    """
    from copy import deepcopy
    result = deepcopy(data)
    assets = {_as_int(row.get("id")) for row in result.get("accounts", []) if row.get("account_type") == "asset"}
    fundings = result.setdefault("life_event_fundings", [])
    next_id = max((_as_int(row.get("id")) or 0 for row in fundings), default=0)
    for event in result.get("life_events", []):
        account_id = _as_int(event.pop("account_id", None))
        if account_id in assets:
            next_id += 1
            fundings.append({"id": next_id, "life_event_id": _as_int(event.get("id")), "account_id": account_id, "share_bp": 10000})
    return result
