from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client
from ..services.accounting_service import calculate_account_journal_balance
from ..services.cache_service import invalidate_client
from ..services.capsule_service import create_capsule_for_goal
from ..services.data_health_service import check_data_health, repair_data_health

router = APIRouter(prefix="/data", tags=["data"])

EXPORT_VERSION = 3

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
    "monthly_reviews",
    "period_reviews",
    "monthly_actions",
    "milestones",
    "capsules",
    "capsule_rules",
    "capsule_holdings",
    "simulation_scenarios",
    "exchange_rates",
]


class ImportPayload(BaseModel):
    version: int | None = None
    exported_at: str | None = None
    manifest: dict[str, Any] | None = None
    client: dict[str, Any] | None = None
    data: dict[str, list[dict[str, Any]]]


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row(obj: Any, fields: list[str]) -> dict[str, Any]:
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


def _data_counts(data: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {key: len(data.get(key, [])) for key in DATA_COLLECTIONS}


def _table_checksums(data: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    return {key: _sha256(data.get(key, [])) for key in DATA_COLLECTIONS}


def _db_revision(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None


def _build_manifest(
    db: Session,
    current_client: models.Client,
    data: dict[str, list[dict[str, Any]]],
    exported_at: str,
) -> dict[str, Any]:
    checksums = _table_checksums(data)
    return {
        "export_version": EXPORT_VERSION,
        "exported_at": exported_at,
        "application": "AssetManagement",
        "alembic_revision": _db_revision(db),
        "client_id": current_client.id,
        "counts": _data_counts(data),
        "checksums": checksums,
        "payload_checksum": _sha256({"data": data, "checksums": checksums}),
    }


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _parse_datetime(value: Any) -> datetime | None:
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


def _validate_import_payload(payload: ImportPayload) -> dict[str, Any]:
    data = payload.data or {}
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

    if payload.version and payload.version > EXPORT_VERSION:
        issue(
            "error",
            "unsupported_version",
            f"Export version {payload.version} is newer than supported version {EXPORT_VERSION}.",
        )
    elif payload.version and payload.version < EXPORT_VERSION:
        issue(
            "warning",
            "older_version",
            f"Export version {payload.version} will be imported with compatibility defaults.",
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
    check_ref("recurring_transactions", "source_registry_entry_id", "registry_entries")
    check_ref("registry_entries", "budget_account_id", "accounts")
    check_ref("registry_entries", "source_account_id", "accounts")
    check_ref("registry_entries", "destination_account_id", "accounts")
    check_ref("registry_entries", "funding_capsule_id", "capsules")
    check_ref("registry_entries", "source_product_id", "products")
    check_ref("registry_entries", "source_recurring_transaction_id", "recurring_transactions")
    check_ref("quick_templates", "default_from_account_id", "accounts")
    check_ref("quick_templates", "default_to_account_id", "accounts")
    check_ref("transaction_batches", "quick_template_id", "quick_templates")
    check_ref("transactions", "from_account_id", "accounts")
    check_ref("transactions", "to_account_id", "accounts")
    check_ref("transactions", "batch_id", "transaction_batches")
    check_ref("journal_entries", "transaction_id", "transactions", required=True)
    check_ref("journal_entries", "account_id", "accounts", required=True)
    check_ref("milestones", "life_event_id", "life_events")
    check_ref("capsules", "account_id", "accounts")
    check_ref("capsules", "life_event_id", "life_events")
    check_ref("capsule_rules", "capsule_id", "capsules", required=True)
    check_ref("capsule_rules", "source_account_id", "accounts")
    check_ref("capsule_holdings", "capsule_id", "capsules", required=True)
    check_ref("capsule_holdings", "account_id", "accounts", required=True)
    check_ref("simulation_scenarios", "life_event_id", "life_events", required=True)
    check_ref("monthly_plan_lines", "account_id", "accounts")
    check_ref("monthly_plan_lines", "source_account_id", "accounts")
    check_ref("monthly_plan_lines", "recurring_transaction_id", "recurring_transactions")
    check_ref("monthly_plan_lines", "plan_id", "budget_plans")

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

    manifest = payload.manifest or {}
    expected_counts = manifest.get("counts") or {}
    actual_counts = _data_counts(data)
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
        "counts": _data_counts(data),
        "issues": issues,
    }


def _remap_nested_ids(value: Any, key_maps: dict[str, dict[int, int]]) -> Any:
    if isinstance(value, list):
        return [_remap_nested_ids(item, key_maps) for item in value]
    if not isinstance(value, dict):
        return value

    mapped: dict[str, Any] = {}
    for key, item_value in value.items():
        id_map = key_maps.get(key)
        old_id = _as_int(item_value)
        if id_map is not None and old_id is not None:
            mapped[key] = id_map.get(old_id, item_value)
        else:
            mapped[key] = _remap_nested_ids(item_value, key_maps)
    return mapped


def _remap_action_target_id(item: dict[str, Any], key_maps: dict[str, dict[int, int]]) -> int | None:
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


@router.get("/export")
def export_client_data(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    tx_ids = [
        row[0]
        for row in db.query(models.Transaction.id)
        .filter(models.Transaction.client_id == current_client.id)
        .all()
    ]

    exported_at = datetime.utcnow().isoformat()
    data = {
            "accounts": [
                _row(
                    account,
                    [
                        "id",
                        "name",
                        "account_type",
                        "balance",
                        "parent_id",
                        "expected_return",
                        "role",
                        "role_target_amount",
                        "is_active",
                    ],
                )
                for account in db.query(models.Account)
                .filter(models.Account.client_id == current_client.id)
                .order_by(models.Account.id)
                .all()
            ],
            "products": [
                _row(
                    product,
                    [
                        "id",
                        "name",
                        "category",
                        "location",
                        "last_unit_price",
                        "units_per_purchase",
                        "frequency_days",
                        "last_purchase_date",
                        "is_asset",
                        "lifespan_months",
                        "budget_account_id",
                        "funding_capsule_id",
                        "budget_treatment",
                        "purchase_price",
                        "purchase_date",
                    ],
                )
                for product in db.query(models.Product)
                .filter(models.Product.client_id == current_client.id)
                .order_by(models.Product.id)
                .all()
            ],
            "simulation_configs": [
                _row(
                    config,
                    [
                        "id",
                        "user_id",
                        "annual_return",
                        "tax_rate",
                        "is_nisa",
                        "monthly_savings",
                        "volatility",
                        "inflation_rate",
                    ],
                )
                for config in db.query(models.SimulationConfig)
                .filter(models.SimulationConfig.client_id == current_client.id)
                .order_by(models.SimulationConfig.id)
                .all()
            ],
            "recurring_transactions": [
                _row(
                    item,
                    [
                        "id",
                        "name",
                        "amount",
                        "currency",
                        "type",
                        "from_account_id",
                        "to_account_id",
                        "frequency",
                        "day_of_month",
                        "month_of_year",
                        "next_due_date",
                        "start_period",
                        "end_period",
                        "auto_post",
                        "is_active",
                        "source_registry_entry_id",
                        "created_at",
                    ],
                )
                for item in db.query(models.RecurringTransaction)
                .filter(models.RecurringTransaction.client_id == current_client.id)
                .order_by(models.RecurringTransaction.id)
                .all()
            ],
            "registry_entries": [
                _row(
                    item,
                    [
                        "id",
                        "name",
                        "entry_type",
                        "category",
                        "amount",
                        "currency",
                        "frequency",
                        "frequency_days",
                        "day_of_month",
                        "month_of_year",
                        "transaction_type",
                        "line_type",
                        "budget_account_id",
                        "source_account_id",
                        "destination_account_id",
                        "funding_capsule_id",
                        "budget_treatment",
                        "generate_recurring",
                        "budget_active",
                        "is_active",
                        "source_product_id",
                        "source_recurring_transaction_id",
                        "note",
                        "start_period",
                        "end_period",
                        "created_at",
                        "updated_at",
                    ],
                )
                for item in db.query(models.RegistryEntry)
                .filter(models.RegistryEntry.client_id == current_client.id)
                .order_by(models.RegistryEntry.id)
                .all()
            ],
            "quick_templates": [
                _row(
                    item,
                    [
                        "id",
                        "tray",
                        "name",
                        "template_kind",
                        "description",
                        "category",
                        "default_currency",
                        "default_from_account_id",
                        "default_to_account_id",
                        "config",
                        "sort_order",
                        "is_active",
                        "created_at",
                        "updated_at",
                    ],
                )
                for item in db.query(models.QuickTemplate)
                .filter(models.QuickTemplate.client_id == current_client.id)
                .order_by(models.QuickTemplate.id)
                .all()
            ],
            "transaction_batches": [
                _row(
                    item,
                    [
                        "id",
                        "quick_template_id",
                        "label",
                        "source",
                        "input_payload",
                        "created_at",
                    ],
                )
                for item in db.query(models.TransactionBatch)
                .filter(models.TransactionBatch.client_id == current_client.id)
                .order_by(models.TransactionBatch.id)
                .all()
            ],
            "life_events": [
                _row(
                    event,
                    [
                        "id",
                        "name",
                        "start_date",
                        "target_date",
                        "target_amount",
                        "priority",
                        "note",
                        "active_plan_basis",
                        "active_plan_label",
                        "plan_status_override",
                        "created_at",
                    ],
                )
                for event in db.query(models.LifeEvent)
                .filter(models.LifeEvent.client_id == current_client.id)
                .order_by(models.LifeEvent.id)
                .all()
            ],
            "transactions": [
                _row(
                    transaction,
                    [
                        "id",
                        "date",
                        "description",
                        "amount",
                        "type",
                        "category",
                        "currency",
                        "from_account_id",
                        "to_account_id",
                        "batch_id",
                        "created_at",
                    ],
                )
                for transaction in db.query(models.Transaction)
                .filter(models.Transaction.client_id == current_client.id)
                .order_by(models.Transaction.id)
                .all()
            ],
            "journal_entries": [
                _row(entry, ["id", "transaction_id", "account_id", "debit", "credit"])
                for entry in db.query(models.JournalEntry)
                .filter(models.JournalEntry.transaction_id.in_(tx_ids or [-1]))
                .order_by(models.JournalEntry.id)
                .all()
            ],
            "budget_plans": [
                _row(
                    plan,
                    [
                        "id",
                        "name",
                        "description",
                        "is_default",
                        "sort_order",
                        "created_at",
                        "updated_at",
                    ],
                )
                for plan in db.query(models.BudgetPlan)
                .filter(models.BudgetPlan.client_id == current_client.id)
                .order_by(models.BudgetPlan.sort_order, models.BudgetPlan.id)
                .all()
            ],
            "monthly_plan_lines": [
                _row(
                    line,
                    [
                        "id",
                        "target_period",
                        "line_type",
                        "target_type",
                        "target_id",
                        "account_id",
                        "source_account_id",
                        "name",
                        "amount",
                        "source",
                        "cash_treatment",
                        "recurring_transaction_id",
                        "plan_id",
                        "is_active",
                        "created_at",
                        "updated_at",
                    ],
                )
                for line in db.query(models.MonthlyPlanLine)
                .filter(models.MonthlyPlanLine.client_id == current_client.id)
                .order_by(models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id)
                .all()
            ],
            "monthly_reviews": [
                _row(
                    review,
                    [
                        "id",
                        "target_period",
                        "reflection",
                        "next_actions",
                        "created_at",
                        "updated_at",
                    ],
                )
                for review in db.query(models.MonthlyReview)
                .filter(models.MonthlyReview.client_id == current_client.id)
                .order_by(models.MonthlyReview.target_period)
                .all()
            ],
            "period_reviews": [
                _row(
                    review,
                    [
                        "id",
                        "start_date",
                        "end_date",
                        "label",
                        "reflection",
                        "next_actions",
                        "created_at",
                        "updated_at",
                    ],
                )
                for review in db.query(models.PeriodReview)
                .filter(models.PeriodReview.client_id == current_client.id)
                .order_by(models.PeriodReview.start_date, models.PeriodReview.end_date)
                .all()
            ],
            "monthly_actions": [
                _row(
                    action,
                    [
                        "id",
                        "source_period",
                        "target_period",
                        "proposal_id",
                        "kind",
                        "description",
                        "amount",
                        "target_id",
                        "payload",
                        "result",
                        "status",
                        "idempotency_key",
                        "created_at",
                        "applied_at",
                    ],
                )
                for action in db.query(models.MonthlyAction)
                .filter(models.MonthlyAction.client_id == current_client.id)
                .order_by(models.MonthlyAction.id)
                .all()
            ],
            "milestones": [
                _row(
                    milestone,
                    [
                        "id",
                        "life_event_id",
                        "date",
                        "target_amount",
                        "note",
                        "source",
                        "source_snapshot",
                        "is_active_plan",
                        "created_at",
                    ],
                )
                for milestone in db.query(models.Milestone)
                .filter(models.Milestone.client_id == current_client.id)
                .order_by(models.Milestone.id)
                .all()
            ],
            "capsules": [
                _row(
                    capsule,
                    [
                        "id",
                        "name",
                        "target_amount",
                        "monthly_contribution",
                        "current_balance",
                        "account_id",
                        "life_event_id",
                        "capsule_type",
                        "target_amount_source",
                        "monthly_contribution_source",
                        "created_at",
                    ],
                )
                for capsule in db.query(models.Capsule)
                .filter(models.Capsule.client_id == current_client.id)
                .order_by(models.Capsule.id)
                .all()
            ],
            "capsule_rules": [
                _row(
                    rule,
                    [
                        "id",
                        "capsule_id",
                        "trigger_type",
                        "trigger_category",
                        "trigger_description",
                        "source_mode",
                        "source_account_id",
                        "amount_type",
                        "amount_value",
                        "is_active",
                        "created_at",
                    ],
                )
                for rule in db.query(models.CapsuleRule)
                .filter(models.CapsuleRule.client_id == current_client.id)
                .order_by(models.CapsuleRule.id)
                .all()
            ],
            "capsule_holdings": [
                _row(holding, ["id", "capsule_id", "account_id", "held_amount", "note", "updated_at"])
                for holding in db.query(models.CapsuleHolding)
                .join(models.Capsule, models.Capsule.id == models.CapsuleHolding.capsule_id)
                .filter(models.Capsule.client_id == current_client.id)
                .order_by(models.CapsuleHolding.id)
                .all()
            ],
            "simulation_scenarios": [
                _row(
                    scenario,
                    [
                        "id",
                        "life_event_id",
                        "name",
                        "description",
                        "annual_return",
                        "inflation",
                        "monthly_savings",
                        "contribution_schedule",
                        "allocation_mode",
                        "created_at",
                        "updated_at",
                    ],
                )
                for scenario in db.query(models.SimulationScenario)
                .filter(models.SimulationScenario.client_id == current_client.id)
                .order_by(models.SimulationScenario.id)
                .all()
            ],
            "exchange_rates": [
                _row(
                    rate,
                    [
                        "id",
                        "base_currency",
                        "quote_currency",
                        "rate",
                        "as_of_date",
                        "source",
                        "created_at",
                        "updated_at",
                    ],
                )
                for rate in db.query(models.ExchangeRate)
                .filter(models.ExchangeRate.client_id == current_client.id)
                .order_by(models.ExchangeRate.id)
                .all()
            ],
    }

    return {
        "version": EXPORT_VERSION,
        "exported_at": exported_at,
        "manifest": _build_manifest(db, current_client, data, exported_at),
        "client": {
            "id": current_client.id,
            "name": current_client.name,
            "username": current_client.username,
            "email": current_client.email,
            "general_settings": current_client.general_settings or {},
        },
        "health": check_data_health(db, current_client.id),
        "data": data,
    }


@router.post("/import/validate")
def validate_import_client_data(
    payload: ImportPayload,
    current_client: models.Client = Depends(get_current_client),
):
    validation = _validate_import_payload(payload)
    return {
        **validation,
        "client": {
            "target_client_id": current_client.id,
            "source_client_id": (payload.client or {}).get("id"),
            "source_name": (payload.client or {}).get("name"),
        },
    }


@router.post("/import")
def import_client_data(
    payload: ImportPayload,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    data = payload.data or {}
    validation = _validate_import_payload(payload)
    if validation["error_count"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Import payload validation failed",
                "validation": validation,
            },
        )

    account_map: dict[int, int] = {}
    transaction_map: dict[int, int] = {}
    batch_map: dict[int, int] = {}
    event_map: dict[int, int] = {}
    quick_template_map: dict[int, int] = {}
    recurring_map: dict[int, int] = {}
    capsule_map: dict[int, int] = {}
    budget_plan_map: dict[int, int] = {}

    try:
        tx_ids = [
            row[0]
            for row in db.query(models.Transaction.id)
            .filter(models.Transaction.client_id == current_client.id)
            .all()
        ]

        if tx_ids:
            db.query(models.JournalEntry).filter(
                models.JournalEntry.transaction_id.in_(tx_ids)
            ).delete(synchronize_session=False)

        capsule_ids = [
            row[0]
            for row in db.query(models.Capsule.id)
            .filter(models.Capsule.client_id == current_client.id)
            .all()
        ]
        if capsule_ids:
            db.query(models.CapsuleHolding).filter(
                models.CapsuleHolding.capsule_id.in_(capsule_ids)
            ).delete(synchronize_session=False)

        for model in [
            models.MonthlyPlanLine,
            models.MonthlyReview,
            models.PeriodReview,
            models.MonthlyAction,
            models.CapsuleRule,
            models.Capsule,
            models.ExchangeRate,
            models.Milestone,
            models.RegistryEntry,
            models.RecurringTransaction,
            models.SimulationScenario,
            models.SimulationConfig,
            models.Product,
            models.Transaction,
            models.TransactionBatch,
            models.QuickTemplate,
            models.BudgetPlan,
            models.LifeEvent,
            models.Account,
        ]:
            db.query(model).filter(model.client_id == current_client.id).delete(
                synchronize_session=False
            )

        db.flush()

        account_parent_updates: list[tuple[models.Account, int]] = []
        for item in data.get("accounts", []):
            old_id = int(item["id"])
            account = models.Account(
                client_id=current_client.id,
                name=item["name"],
                account_type=item["account_type"],
                balance=0,
                expected_return=item.get("expected_return") or 0.0,
                role=item.get("role", "unassigned"),
                role_target_amount=item.get("role_target_amount"),
                is_active=item.get("is_active", True),
            )
            db.add(account)
            db.flush()
            account_map[old_id] = account.id
            if item.get("parent_id"):
                account_parent_updates.append((account, int(item["parent_id"])))

        for account, old_parent_id in account_parent_updates:
            account.parent_id = account_map.get(old_parent_id)

        for item in data.get("budget_plans", []):
            old_id = int(item["id"])
            plan = models.BudgetPlan(
                client_id=current_client.id,
                name=item["name"],
                description=item.get("description"),
                is_default=item.get("is_default", False),
                sort_order=item.get("sort_order") or 0,
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_datetime(item.get("updated_at")),
            )
            db.add(plan)
            db.flush()
            budget_plan_map[old_id] = plan.id

        product_map: dict[int, int] = {}
        product_funding_updates: list[tuple[models.Product, int]] = []
        for item in data.get("products", []):
            old_id = int(item["id"])
            product = models.Product(
                client_id=current_client.id,
                name=item["name"],
                category=item["category"],
                location=item.get("location"),
                last_unit_price=item.get("last_unit_price") or 0,
                units_per_purchase=item.get("units_per_purchase") or 1,
                frequency_days=item.get("frequency_days") or 0,
                last_purchase_date=_parse_date(item.get("last_purchase_date")),
                is_asset=item.get("is_asset", False),
                lifespan_months=item.get("lifespan_months"),
                budget_account_id=account_map.get(item.get("budget_account_id")),
                budget_treatment=item.get("budget_treatment") or "auto",
                purchase_price=item.get("purchase_price"),
                purchase_date=_parse_date(item.get("purchase_date")),
            )
            db.add(product)
            db.flush()
            product_map[old_id] = product.id
            if item.get("funding_capsule_id"):
                product_funding_updates.append((product, int(item["funding_capsule_id"])))

        for item in data.get("simulation_configs", []):
            db.add(
                models.SimulationConfig(
                    client_id=current_client.id,
                    user_id=item.get("user_id", current_client.id),
                    annual_return=item.get("annual_return", 5.0),
                    tax_rate=item.get("tax_rate", 20.0),
                    is_nisa=item.get("is_nisa", True),
                    monthly_savings=item.get("monthly_savings", 100000),
                    volatility=item.get("volatility", 15.0),
                    inflation_rate=item.get("inflation_rate", 2.0),
                )
            )

        for item in data.get("recurring_transactions", []):
            old_id = int(item["id"])
            recurring = models.RecurringTransaction(
                client_id=current_client.id,
                name=item["name"],
                amount=item.get("amount") or 0,
                currency=item.get("currency") or "JPY",
                type=item["type"],
                from_account_id=account_map.get(item.get("from_account_id")),
                to_account_id=account_map.get(item.get("to_account_id")),
                frequency=item["frequency"],
                day_of_month=item.get("day_of_month") or 1,
                month_of_year=item.get("month_of_year"),
                next_due_date=_parse_date(item.get("next_due_date")),
                start_period=item.get("start_period"),
                end_period=item.get("end_period"),
                auto_post=item.get("auto_post", True),
                is_active=item.get("is_active", True),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(recurring)
            db.flush()
            recurring_map[old_id] = recurring.id

        registry_map: dict[int, int] = {}
        registry_funding_updates: list[tuple[models.RegistryEntry, int]] = []
        for item in data.get("registry_entries", []):
            old_id = int(item["id"])
            entry = models.RegistryEntry(
                client_id=current_client.id,
                name=item["name"],
                entry_type=item.get("entry_type") or "service",
                category=item.get("category"),
                amount=item.get("amount") or 0,
                currency=item.get("currency") or "JPY",
                frequency=item.get("frequency") or "Monthly",
                frequency_days=item.get("frequency_days"),
                day_of_month=item.get("day_of_month") or 1,
                month_of_year=item.get("month_of_year"),
                transaction_type=item.get("transaction_type") or "Expense",
                line_type=item.get("line_type") or "expense",
                budget_account_id=account_map.get(item.get("budget_account_id")),
                source_account_id=account_map.get(item.get("source_account_id")),
                destination_account_id=account_map.get(item.get("destination_account_id")),
                funding_capsule_id=capsule_map.get(item.get("funding_capsule_id")),
                budget_treatment=item.get("budget_treatment") or "expense_only",
                generate_recurring=item.get("generate_recurring", False),
                budget_active=item.get("budget_active", True),
                is_active=item.get("is_active", True),
                source_product_id=product_map.get(item.get("source_product_id")),
                source_recurring_transaction_id=recurring_map.get(item.get("source_recurring_transaction_id")),
                note=item.get("note"),
                start_period=item.get("start_period"),
                end_period=item.get("end_period"),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_datetime(item.get("updated_at")),
            )
            db.add(entry)
            db.flush()
            registry_map[old_id] = entry.id
            if item.get("funding_capsule_id"):
                registry_funding_updates.append((entry, int(item["funding_capsule_id"])))

        for item in data.get("recurring_transactions", []):
            source_registry_id = registry_map.get(item.get("source_registry_entry_id"))
            if source_registry_id and (recurring_id := recurring_map.get(int(item["id"]))):
                recurring = db.query(models.RecurringTransaction).filter(
                    models.RecurringTransaction.id == recurring_id,
                    models.RecurringTransaction.client_id == current_client.id,
                ).first()
                if recurring:
                    recurring.source_registry_entry_id = source_registry_id

        for item in data.get("quick_templates", []):
            old_id = int(item["id"])
            template = models.QuickTemplate(
                client_id=current_client.id,
                tray=item["tray"],
                name=item["name"],
                template_kind=item["template_kind"],
                description=item.get("description"),
                category=item.get("category"),
                default_currency=item.get("default_currency") or "JPY",
                default_from_account_id=account_map.get(item.get("default_from_account_id")),
                default_to_account_id=account_map.get(item.get("default_to_account_id")),
                config=item.get("config") or {},
                sort_order=item.get("sort_order") or 0,
                is_active=item.get("is_active", True),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_datetime(item.get("updated_at")),
            )
            db.add(template)
            db.flush()
            quick_template_map[old_id] = template.id

        for item in data.get("transaction_batches", []):
            old_id = int(item["id"])
            batch = models.TransactionBatch(
                client_id=current_client.id,
                quick_template_id=quick_template_map.get(item.get("quick_template_id")),
                label=item.get("label"),
                source=item.get("source") or "quick",
                input_payload=item.get("input_payload") or {},
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(batch)
            db.flush()
            batch_map[old_id] = batch.id

        for item in data.get("life_events", []):
            old_id = int(item["id"])
            event = models.LifeEvent(
                client_id=current_client.id,
                name=item["name"],
                start_date=_parse_date(item.get("start_date")),
                target_date=_parse_date(item.get("target_date")),
                target_amount=item.get("target_amount") or 0,
                priority=item.get("priority") or 2,
                note=item.get("note"),
                active_plan_basis=item.get("active_plan_basis") or "milestone",
                active_plan_label=item.get("active_plan_label"),
                plan_status_override=item.get("plan_status_override"),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(event)
            db.flush()
            event_map[old_id] = event.id

        for item in data.get("transactions", []):
            old_id = int(item["id"])
            transaction = models.Transaction(
                client_id=current_client.id,
                date=_parse_date(item.get("date")),
                description=item["description"],
                amount=item.get("amount") or 0,
                type=item["type"],
                category=item.get("category"),
                currency=item.get("currency") or "JPY",
                from_account_id=account_map.get(item.get("from_account_id")),
                to_account_id=account_map.get(item.get("to_account_id")),
                batch_id=batch_map.get(item.get("batch_id")),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(transaction)
            db.flush()
            transaction_map[old_id] = transaction.id

        for item in data.get("journal_entries", []):
            transaction_id = transaction_map.get(item.get("transaction_id"))
            account_id = account_map.get(item.get("account_id"))
            if transaction_id and account_id:
                db.add(
                    models.JournalEntry(
                        transaction_id=transaction_id,
                        account_id=account_id,
                        debit=item.get("debit") or 0,
                        credit=item.get("credit") or 0,
                    )
                )

        db.flush()
        for account in db.query(models.Account).filter(models.Account.client_id == current_client.id).all():
            account.balance = calculate_account_journal_balance(db, account)

        for item in data.get("monthly_reviews", []):
            db.add(
                models.MonthlyReview(
                    client_id=current_client.id,
                    target_period=item["target_period"],
                    reflection=item.get("reflection") or "",
                    next_actions=item.get("next_actions") or "",
                    created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(item.get("updated_at")),
                )
            )

        for item in data.get("period_reviews", []):
            db.add(
                models.PeriodReview(
                    client_id=current_client.id,
                    start_date=_parse_date(item.get("start_date")),
                    end_date=_parse_date(item.get("end_date")),
                    label=item.get("label") or "",
                    reflection=item.get("reflection") or "",
                    next_actions=item.get("next_actions") or "",
                    created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(item.get("updated_at")),
                )
            )

        milestone_map: dict[int, int] = {}
        for item in data.get("milestones", []):
            old_id = int(item["id"])
            milestone = models.Milestone(
                client_id=current_client.id,
                life_event_id=event_map.get(item.get("life_event_id")),
                date=_parse_date(item.get("date")),
                target_amount=item.get("target_amount") or 0,
                note=item.get("note"),
                source=item.get("source") or "manual",
                source_snapshot=item.get("source_snapshot"),
                is_active_plan=item.get("is_active_plan", True),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(milestone)
            db.flush()
            milestone_map[old_id] = milestone.id

        for item in data.get("simulation_scenarios", []):
            life_event_id = event_map.get(item.get("life_event_id"))
            if life_event_id:
                db.add(
                    models.SimulationScenario(
                        client_id=current_client.id,
                        life_event_id=life_event_id,
                        name=item["name"],
                        description=item.get("description"),
                        annual_return=item.get("annual_return") or 5.0,
                        inflation=item.get("inflation") or 2.0,
                        monthly_savings=item.get("monthly_savings"),
                        contribution_schedule=item.get("contribution_schedule") or [],
                        allocation_mode=item.get("allocation_mode") or "direct",
                        created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                        updated_at=_parse_datetime(item.get("updated_at")),
                    )
                )

        for item in data.get("capsules", []):
            old_id = int(item["id"])
            capsule = models.Capsule(
                client_id=current_client.id,
                name=item["name"],
                target_amount=item.get("target_amount") or 0,
                monthly_contribution=item.get("monthly_contribution") or 0,
                current_balance=item.get("current_balance") or 0,
                account_id=account_map.get(item.get("account_id")),
                life_event_id=event_map.get(item.get("life_event_id")),
                capsule_type=item.get("capsule_type") or ("life_event" if item.get("life_event_id") else "manual"),
                target_amount_source=item.get("target_amount_source") or "manual",
                monthly_contribution_source=item.get("monthly_contribution_source") or "manual",
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(capsule)
            db.flush()
            capsule_map[old_id] = capsule.id

        for product, old_capsule_id in product_funding_updates:
            product.funding_capsule_id = capsule_map.get(old_capsule_id)

        for registry_entry, old_capsule_id in registry_funding_updates:
            registry_entry.funding_capsule_id = capsule_map.get(old_capsule_id)

        # Recreate missing goal capsules so older exports behave like normal goal creation.
        for event in (
            db.query(models.LifeEvent)
            .filter(models.LifeEvent.client_id == current_client.id)
            .all()
        ):
            create_capsule_for_goal(db, current_client.id, event)

        for item in data.get("capsule_rules", []):
            capsule_id = capsule_map.get(item.get("capsule_id"))
            if capsule_id:
                db.add(
                    models.CapsuleRule(
                        client_id=current_client.id,
                        capsule_id=capsule_id,
                        trigger_type=item["trigger_type"],
                        trigger_category=item.get("trigger_category"),
                        trigger_description=item.get("trigger_description"),
                        source_mode=item.get("source_mode") or "transaction_account",
                        source_account_id=account_map.get(item.get("source_account_id")),
                        amount_type=item.get("amount_type") or "fixed",
                        amount_value=item.get("amount_value") or 0,
                        is_active=item.get("is_active", True),
                        created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    )
                )

        for item in data.get("capsule_holdings", []):
            capsule_id = capsule_map.get(item.get("capsule_id"))
            account_id = account_map.get(item.get("account_id"))
            if capsule_id and account_id:
                db.add(
                    models.CapsuleHolding(
                        capsule_id=capsule_id,
                        account_id=account_id,
                        held_amount=item.get("held_amount") or 0,
                        note=item.get("note"),
                        updated_at=_parse_datetime(item.get("updated_at")) or datetime.utcnow(),
                    )
                )

        monthly_plan_line_map: dict[int, int] = {}
        for item in data.get("monthly_plan_lines", []):
            old_id = int(item["id"])
            target_type = item.get("target_type") or "manual"
            target_id = item.get("target_id")
            if target_type == "capsule":
                target_id = capsule_map.get(target_id)
            elif target_type == "life_event":
                target_id = event_map.get(target_id)
            elif target_type == "product":
                target_id = product_map.get(target_id)
            elif target_type == "account":
                target_id = account_map.get(target_id)
            line = models.MonthlyPlanLine(
                client_id=current_client.id,
                target_period=item["target_period"],
                line_type=item["line_type"],
                target_type=target_type,
                target_id=target_id,
                account_id=account_map.get(item.get("account_id")),
                source_account_id=account_map.get(item.get("source_account_id")),
                name=item.get("name"),
                amount=item.get("amount") or 0,
                source=item.get("source") or "manual",
                cash_treatment=item.get("cash_treatment") or "auto",
                recurring_transaction_id=recurring_map.get(item.get("recurring_transaction_id")),
                plan_id=budget_plan_map.get(item.get("plan_id")),
                is_active=item.get("is_active", True),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_datetime(item.get("updated_at")),
            )
            db.add(line)
            db.flush()
            monthly_plan_line_map[old_id] = line.id

        for item in data.get("exchange_rates", []):
            db.add(
                models.ExchangeRate(
                    client_id=current_client.id,
                    base_currency=(item.get("base_currency") or "JPY").upper(),
                    quote_currency=(item.get("quote_currency") or "JPY").upper(),
                    rate=item.get("rate") or 1.0,
                    as_of_date=_parse_date(item.get("as_of_date")) or date.today(),
                    source=item.get("source") or "manual",
                    created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=_parse_datetime(item.get("updated_at")),
                )
            )

        action_key_maps = {
            "account_id": account_map,
            "from_account_id": account_map,
            "to_account_id": account_map,
            "source_account_id": account_map,
            "destination_account_id": account_map,
            "budget_account_id": account_map,
            "recurring_id": recurring_map,
            "recurring_transaction_id": recurring_map,
            "source_recurring_transaction_id": recurring_map,
            "life_event_id": event_map,
            "capsule_id": capsule_map,
            "funding_capsule_id": capsule_map,
            "product_id": product_map,
            "source_product_id": product_map,
            "transaction_id": transaction_map,
            "batch_id": batch_map,
            "quick_template_id": quick_template_map,
            "budget_plan_id": budget_plan_map,
            "plan_id": budget_plan_map,
            "plan_line_id": monthly_plan_line_map,
            "monthly_plan_line_id": monthly_plan_line_map,
            "milestone_id": milestone_map,
        }
        for item in data.get("monthly_actions", []):
            db.add(
                models.MonthlyAction(
                    client_id=current_client.id,
                    source_period=item["source_period"],
                    target_period=item.get("target_period"),
                    proposal_id=item["proposal_id"],
                    kind=item["kind"],
                    description=item.get("description") or "",
                    amount=item.get("amount"),
                    target_id=_remap_action_target_id(item, action_key_maps),
                    payload=_remap_nested_ids(item.get("payload") or {}, action_key_maps),
                    result=_remap_nested_ids(item.get("result") or {}, action_key_maps),
                    status=item.get("status") or "pending",
                    idempotency_key=item.get("idempotency_key") or f"import:{current_client.id}:{item['id']}",
                    created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    applied_at=_parse_datetime(item.get("applied_at")),
                )
            )

        db.commit()
        invalidate_client(current_client.id)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc

    return {
        "status": "ok",
        "message": "Data imported successfully",
        "counts": _data_counts(data),
        "validation": validation,
        "health": check_data_health(db, current_client.id),
    }


@router.get("/health")
def data_health_check(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return check_data_health(db, current_client.id)


@router.post("/health/repair")
def data_health_repair(
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    return repair_data_health(db, current_client.id)
