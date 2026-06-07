from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from .ai_policy_service import SENSITIVE_KEY_PARTS
from .analysis_service import get_summary

AiDataClassification = Literal["normal", "sensitive", "secret"]

CATALOG_VERSION = "2026-06-08"


@dataclass(frozen=True)
class AiContextResourceDescriptor:
    resource: str
    title: str
    description: str
    classification: AiDataClassification
    available: bool
    risk: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    default_limit: int | None = None


SECRET_EXCLUDES = (
    "credential_secrets",
    "auth_tokens",
    "mfa_and_recovery_secrets",
)

AI_CONTEXT_CATALOG: tuple[AiContextResourceDescriptor, ...] = (
    AiContextResourceDescriptor(
        resource="summary",
        title="Financial summary",
        description="Aggregated KPIs and current-month financial indicators for AI analysis.",
        classification="normal",
        available=True,
        risk="low",
        includes=("aggregated_kpis", "monthly_summary", "category_aggregation"),
        excludes=SECRET_EXCLUDES,
    ),
    AiContextResourceDescriptor(
        resource="accounts",
        title="Accounts",
        description="Active account metadata and balances.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("account_id", "name", "type", "balance", "role"),
        excludes=SECRET_EXCLUDES,
        default_limit=200,
    ),
    AiContextResourceDescriptor(
        resource="transactions_recent",
        title="Recent transactions",
        description="Newest transactions for short-term analysis and categorization support.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("transaction_id", "date", "description", "amount", "type", "category", "accounts"),
        excludes=SECRET_EXCLUDES,
        default_limit=50,
    ),
    AiContextResourceDescriptor(
        resource="monthly_plan",
        title="Monthly plan",
        description="Active monthly plan lines for a target period.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("target_period", "line_type", "name", "amount", "account_refs"),
        excludes=SECRET_EXCLUDES,
        default_limit=200,
    ),
    AiContextResourceDescriptor(
        resource="recurring_transactions",
        title="Recurring transactions",
        description="Active recurring transaction definitions.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("name", "amount", "type", "frequency", "next_due_date", "account_refs"),
        excludes=SECRET_EXCLUDES,
        default_limit=100,
    ),
    AiContextResourceDescriptor(
        resource="goals",
        title="Life events and goals",
        description="Life-event goals and target amounts.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("name", "target_date", "target_amount", "priority", "plan_status"),
        excludes=SECRET_EXCLUDES,
        default_limit=100,
    ),
    AiContextResourceDescriptor(
        resource="products",
        title="Products",
        description="Product and item registry data for purchase planning.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("name", "category", "unit_price", "frequency", "budget_treatment"),
        excludes=SECRET_EXCLUDES,
        default_limit=100,
    ),
    AiContextResourceDescriptor(
        resource="registry_entries",
        title="Registry entries",
        description="Recurring cash-flow assumptions and budget registry entries.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("name", "entry_type", "amount", "frequency", "line_type", "budget_treatment"),
        excludes=SECRET_EXCLUDES,
        default_limit=100,
    ),
    AiContextResourceDescriptor(
        resource="settings",
        title="Non-secret settings",
        description="Client identity and non-secret settings visible to AI.",
        classification="normal",
        available=True,
        risk="low",
        includes=("client_id", "name", "general_settings", "ai_key_configured", "mfa_enabled"),
        excludes=SECRET_EXCLUDES,
    ),
    AiContextResourceDescriptor(
        resource="audit_logs",
        title="AI audit logs",
        description="Recent AI operation audit metadata with request/result summaries already redacted.",
        classification="sensitive",
        available=True,
        risk="low",
        includes=("created_at", "source", "tool_name", "resource", "action", "risk", "decision"),
        excludes=SECRET_EXCLUDES,
        default_limit=50,
    ),
    AiContextResourceDescriptor(
        resource="data_export",
        title="Data export",
        description="Full export is a critical operation and is not available through normal AI context APIs.",
        classification="secret",
        available=False,
        risk="critical",
        includes=(),
        excludes=("full_database_export",) + SECRET_EXCLUDES,
    ),
)


def list_context_resources() -> list[dict[str, Any]]:
    return [_descriptor_payload(descriptor) for descriptor in AI_CONTEXT_CATALOG]


def get_context_summary(db: Session, client_id: int) -> dict[str, Any]:
    client = _get_client(db, client_id)
    data = {
        "catalog_version": CATALOG_VERSION,
        "client": _settings_payload(client),
        "summary": get_summary(db, client_id),
        "available_resources": [
            descriptor.resource for descriptor in AI_CONTEXT_CATALOG if descriptor.available
        ],
    }
    return _context_response("summary", data)


def get_context_resource(
    db: Session,
    client_id: int,
    resource: str,
    *,
    limit: int = 50,
    period: str | None = None,
) -> dict[str, Any]:
    descriptor = _get_descriptor(resource)
    if not descriptor.available:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ai_context_resource_unavailable",
                "resource": descriptor.resource,
                "risk": descriptor.risk,
                "reason": descriptor.description,
            },
        )

    effective_limit = _limit(limit, descriptor.default_limit)
    loaders = {
        "summary": lambda: get_summary(db, client_id),
        "accounts": lambda: _accounts(db, client_id, effective_limit),
        "transactions_recent": lambda: _transactions_recent(db, client_id, effective_limit),
        "monthly_plan": lambda: _monthly_plan(db, client_id, period, effective_limit),
        "recurring_transactions": lambda: _recurring_transactions(db, client_id, effective_limit),
        "goals": lambda: _goals(db, client_id, effective_limit),
        "products": lambda: _products(db, client_id, effective_limit),
        "registry_entries": lambda: _registry_entries(db, client_id, effective_limit),
        "settings": lambda: _settings_payload(_get_client(db, client_id)),
        "audit_logs": lambda: _audit_logs(db, client_id, effective_limit),
    }

    try:
        data = loaders[descriptor.resource]()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown AI context resource: {resource}") from exc
    return _context_response(
        descriptor.resource,
        data,
        metadata={"limit": effective_limit, "period": period},
    )


def _context_response(resource: str, data: dict[str, Any] | list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    descriptor = _get_descriptor(resource)
    return _redact_context({
        "resource": descriptor.resource,
        "classification": descriptor.classification,
        "generated_at": datetime.utcnow(),
        "data": data,
        "metadata": {
            "catalog_version": CATALOG_VERSION,
            "includes": list(descriptor.includes),
            "excludes": list(descriptor.excludes),
            **(metadata or {}),
        },
    })


def _descriptor_payload(descriptor: AiContextResourceDescriptor) -> dict[str, Any]:
    payload = asdict(descriptor)
    payload["includes"] = list(descriptor.includes)
    payload["excludes"] = list(descriptor.excludes)
    return payload


def _get_descriptor(resource: str) -> AiContextResourceDescriptor:
    normalized = (resource or "").strip().lower().replace("-", "_")
    for descriptor in AI_CONTEXT_CATALOG:
        if descriptor.resource == normalized:
            return descriptor
    raise HTTPException(status_code=404, detail=f"Unknown AI context resource: {resource}")


def _get_client(db: Session, client_id: int) -> models.Client:
    client = db.get(models.Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _limit(requested: int, default_limit: int | None) -> int:
    base = requested or default_limit or 50
    return max(1, min(int(base), 500))


def _settings_payload(client: models.Client) -> dict[str, Any]:
    return {
        "client_id": client.id,
        "name": client.name,
        "username": client.username,
        "email": client.email,
        "general_settings": client.general_settings or {},
        "ai_key_configured": bool(client.ai_config),
        "mfa_enabled": bool(client.mfa_setting and client.mfa_setting.enabled),
    }


def _account_ref(account: models.Account | None) -> dict[str, Any] | None:
    if account is None:
        return None
    return {
        "id": account.id,
        "name": account.name,
        "account_type": account.account_type,
        "role": account.role,
    }


def _accounts(db: Session, client_id: int, limit: int) -> dict[str, Any]:
    rows = db.query(models.Account).filter(
        models.Account.client_id == client_id,
    ).order_by(models.Account.account_type, models.Account.name).limit(limit).all()
    return {
        "count": len(rows),
        "accounts": [
            {
                "id": account.id,
                "name": account.name,
                "account_type": account.account_type,
                "balance": account.balance,
                "currency": None,
                "parent_id": account.parent_id,
                "expected_return": account.expected_return,
                "role": account.role,
                "role_target_amount": account.role_target_amount,
                "is_active": account.is_active,
            }
            for account in rows
        ],
    }


def _transactions_recent(db: Session, client_id: int, limit: int) -> dict[str, Any]:
    rows = db.query(models.Transaction).filter(
        models.Transaction.client_id == client_id,
    ).order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "transactions": [
            {
                "id": tx.id,
                "date": _iso(tx.date),
                "description": tx.description,
                "amount": tx.amount,
                "type": tx.type,
                "category": tx.category,
                "currency": tx.currency,
                "from_account": _account_ref(tx.from_account_rel),
                "to_account": _account_ref(tx.to_account_rel),
                "created_at": _iso(tx.created_at),
            }
            for tx in rows
        ],
    }


def _monthly_plan(db: Session, client_id: int, period: str | None, limit: int) -> dict[str, Any]:
    target_period = period or date.today().strftime("%Y-%m")
    rows = db.query(models.MonthlyPlanLine).filter(
        models.MonthlyPlanLine.client_id == client_id,
        models.MonthlyPlanLine.target_period == target_period,
        models.MonthlyPlanLine.is_active.is_(True),
    ).order_by(models.MonthlyPlanLine.line_type, models.MonthlyPlanLine.id).limit(limit).all()
    return {
        "target_period": target_period,
        "count": len(rows),
        "lines": [
            {
                "id": line.id,
                "target_period": line.target_period,
                "line_type": line.line_type,
                "target_type": line.target_type,
                "target_id": line.target_id,
                "name": line.name,
                "amount": line.amount,
                "source": line.source,
                "source_kind": line.source_kind,
                "cash_treatment": line.cash_treatment,
                "manual_override": line.manual_override,
                "account": _account_ref(line.account),
                "source_account": _account_ref(line.source_account),
            }
            for line in rows
        ],
    }


def _recurring_transactions(db: Session, client_id: int, limit: int) -> dict[str, Any]:
    rows = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.client_id == client_id,
        models.RecurringTransaction.is_active.is_(True),
    ).order_by(models.RecurringTransaction.next_due_date, models.RecurringTransaction.id).limit(limit).all()
    return {
        "count": len(rows),
        "recurring_transactions": [
            {
                "id": row.id,
                "name": row.name,
                "amount": row.amount,
                "currency": row.currency,
                "type": row.type,
                "frequency": row.frequency,
                "day_of_month": row.day_of_month,
                "month_of_year": row.month_of_year,
                "next_due_date": _iso(row.next_due_date),
                "start_period": row.start_period,
                "end_period": row.end_period,
                "auto_post": row.auto_post,
                "from_account": _account_ref(row.from_account),
                "to_account": _account_ref(row.to_account),
            }
            for row in rows
        ],
    }


def _goals(db: Session, client_id: int, limit: int) -> dict[str, Any]:
    rows = db.query(models.LifeEvent).filter(
        models.LifeEvent.client_id == client_id,
    ).order_by(models.LifeEvent.target_date, models.LifeEvent.id).limit(limit).all()
    return {
        "count": len(rows),
        "goals": [
            {
                "id": row.id,
                "name": row.name,
                "start_date": _iso(row.start_date),
                "target_date": _iso(row.target_date),
                "target_amount": row.target_amount,
                "priority": row.priority,
                "active_plan_basis": row.active_plan_basis,
                "active_plan_label": row.active_plan_label,
                "plan_status_override": row.plan_status_override,
            }
            for row in rows
        ],
    }


def _products(db: Session, client_id: int, limit: int) -> dict[str, Any]:
    rows = db.query(models.Product).filter(
        models.Product.client_id == client_id,
    ).order_by(models.Product.name).limit(limit).all()
    return {
        "count": len(rows),
        "products": [
            {
                "id": row.id,
                "name": row.name,
                "category": row.category,
                "location": row.location,
                "last_unit_price": row.last_unit_price,
                "units_per_purchase": row.units_per_purchase,
                "frequency_days": row.frequency_days,
                "last_purchase_date": _iso(row.last_purchase_date),
                "is_asset": row.is_asset,
                "lifespan_months": row.lifespan_months,
                "budget_treatment": row.budget_treatment,
                "budget_account": _account_ref(row.budget_account),
            }
            for row in rows
        ],
    }


def _registry_entries(db: Session, client_id: int, limit: int) -> dict[str, Any]:
    rows = db.query(models.RegistryEntry).filter(
        models.RegistryEntry.client_id == client_id,
        models.RegistryEntry.is_active.is_(True),
    ).order_by(models.RegistryEntry.name).limit(limit).all()
    return {
        "count": len(rows),
        "registry_entries": [
            {
                "id": row.id,
                "name": row.name,
                "entry_type": row.entry_type,
                "category": row.category,
                "amount": row.amount,
                "currency": row.currency,
                "frequency": row.frequency,
                "day_of_month": row.day_of_month,
                "transaction_type": row.transaction_type,
                "line_type": row.line_type,
                "budget_treatment": row.budget_treatment,
                "budget_active": row.budget_active,
                "start_period": row.start_period,
                "end_period": row.end_period,
                "budget_account": _account_ref(row.budget_account),
                "source_account": _account_ref(row.source_account),
                "destination_account": _account_ref(row.destination_account),
            }
            for row in rows
        ],
    }


def _audit_logs(db: Session, client_id: int, limit: int) -> dict[str, Any]:
    rows = db.query(models.AiAuditLog).filter(
        models.AiAuditLog.client_id == client_id,
    ).order_by(models.AiAuditLog.created_at.desc(), models.AiAuditLog.id.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "audit_logs": [
            {
                "id": row.id,
                "created_at": _iso(row.created_at),
                "source": row.source,
                "tool_name": row.tool_name,
                "resource": row.resource,
                "action": row.action,
                "risk": row.risk,
                "decision": row.decision,
                "mcp_client_id": row.mcp_client_id,
                "request_summary": row.request_summary,
                "result_summary": row.result_summary,
            }
            for row in rows
        ],
    }


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _redact_context(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_redact_context(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                continue
            result[key_text] = _redact_context(item)
        return result
    return str(value)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)
