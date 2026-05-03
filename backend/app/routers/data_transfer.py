from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..dependencies import get_current_client

router = APIRouter(prefix="/data", tags=["data"])


class ImportPayload(BaseModel):
    version: int | None = None
    exported_at: str | None = None
    client: dict[str, Any] | None = None
    data: dict[str, list[dict[str, Any]]]


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _row(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {field: _iso(getattr(obj, field)) for field in fields}


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


def _parse_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


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
    event_ids = [
        row[0]
        for row in db.query(models.LifeEvent.id)
        .filter(models.LifeEvent.client_id == current_client.id)
        .all()
    ]

    return {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat(),
        "client": {
            "id": current_client.id,
            "name": current_client.name,
            "username": current_client.username,
            "email": current_client.email,
            "general_settings": current_client.general_settings or {},
        },
        "data": {
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
                        "type",
                        "from_account_id",
                        "to_account_id",
                        "frequency",
                        "day_of_month",
                        "month_of_year",
                        "next_due_date",
                        "is_active",
                        "created_at",
                    ],
                )
                for item in db.query(models.RecurringTransaction)
                .filter(models.RecurringTransaction.client_id == current_client.id)
                .order_by(models.RecurringTransaction.id)
                .all()
            ],
            "life_events": [
                _row(
                    event,
                    [
                        "id",
                        "name",
                        "target_date",
                        "target_amount",
                        "priority",
                        "note",
                        "created_at",
                    ],
                )
                for event in db.query(models.LifeEvent)
                .filter(models.LifeEvent.client_id == current_client.id)
                .order_by(models.LifeEvent.id)
                .all()
            ],
            "goal_allocations": [
                _row(
                    allocation,
                    ["id", "life_event_id", "account_id", "allocation_percentage"],
                )
                for allocation in db.query(models.GoalAllocation)
                .filter(models.GoalAllocation.life_event_id.in_(event_ids or [-1]))
                .order_by(models.GoalAllocation.id)
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
            "monthly_budgets": [
                _row(budget, ["id", "account_id", "target_period", "amount"])
                for budget in db.query(models.MonthlyBudget)
                .filter(models.MonthlyBudget.client_id == current_client.id)
                .order_by(models.MonthlyBudget.target_period, models.MonthlyBudget.account_id)
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
        },
    }


@router.post("/import")
def import_client_data(
    payload: ImportPayload,
    db: Session = Depends(get_db),
    current_client: models.Client = Depends(get_current_client),
):
    data = payload.data or {}
    account_map: dict[int, int] = {}
    transaction_map: dict[int, int] = {}
    event_map: dict[int, int] = {}

    try:
        tx_ids = [
            row[0]
            for row in db.query(models.Transaction.id)
            .filter(models.Transaction.client_id == current_client.id)
            .all()
        ]
        event_ids = [
            row[0]
            for row in db.query(models.LifeEvent.id)
            .filter(models.LifeEvent.client_id == current_client.id)
            .all()
        ]

        if tx_ids:
            db.query(models.JournalEntry).filter(
                models.JournalEntry.transaction_id.in_(tx_ids)
            ).delete(synchronize_session=False)
        if event_ids:
            db.query(models.GoalAllocation).filter(
                models.GoalAllocation.life_event_id.in_(event_ids)
            ).delete(synchronize_session=False)

        for model in [
            models.MonthlyBudget,
            models.MonthlyReview,
            models.PeriodReview,
            models.CapsuleRule,
            models.Capsule,
            models.Milestone,
            models.RecurringTransaction,
            models.SimulationConfig,
            models.Product,
            models.Transaction,
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
                is_active=item.get("is_active", True),
            )
            db.add(account)
            db.flush()
            account_map[old_id] = account.id
            if item.get("parent_id"):
                account_parent_updates.append((account, int(item["parent_id"])))

        for account, old_parent_id in account_parent_updates:
            account.parent_id = account_map.get(old_parent_id)

        for item in data.get("products", []):
            db.add(
                models.Product(
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
                    purchase_price=item.get("purchase_price"),
                    purchase_date=_parse_date(item.get("purchase_date")),
                )
            )

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
            db.add(
                models.RecurringTransaction(
                    client_id=current_client.id,
                    name=item["name"],
                    amount=item.get("amount") or 0,
                    type=item["type"],
                    from_account_id=account_map.get(item.get("from_account_id")),
                    to_account_id=account_map.get(item.get("to_account_id")),
                    frequency=item["frequency"],
                    day_of_month=item.get("day_of_month") or 1,
                    month_of_year=item.get("month_of_year"),
                    next_due_date=_parse_date(item.get("next_due_date")),
                    is_active=item.get("is_active", True),
                    created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                )
            )

        for item in data.get("life_events", []):
            old_id = int(item["id"])
            event = models.LifeEvent(
                client_id=current_client.id,
                name=item["name"],
                target_date=_parse_date(item.get("target_date")),
                target_amount=item.get("target_amount") or 0,
                priority=item.get("priority") or 2,
                note=item.get("note"),
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(event)
            db.flush()
            event_map[old_id] = event.id

        for item in data.get("goal_allocations", []):
            life_event_id = event_map.get(item.get("life_event_id"))
            account_id = account_map.get(item.get("account_id"))
            if life_event_id and account_id:
                db.add(
                    models.GoalAllocation(
                        life_event_id=life_event_id,
                        account_id=account_id,
                        allocation_percentage=item.get("allocation_percentage") or 0,
                    )
                )

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

        for item in data.get("monthly_budgets", []):
            account_id = account_map.get(item.get("account_id"))
            if account_id:
                db.add(
                    models.MonthlyBudget(
                        id=_parse_uuid(item.get("id")),
                        client_id=current_client.id,
                        account_id=account_id,
                        target_period=item["target_period"],
                        amount=item.get("amount") or 0,
                    )
                )

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

        for item in data.get("milestones", []):
            db.add(
                models.Milestone(
                    client_id=current_client.id,
                    life_event_id=event_map.get(item.get("life_event_id")),
                    date=_parse_date(item.get("date")),
                    target_amount=item.get("target_amount") or 0,
                    note=item.get("note"),
                    source=item.get("source") or "manual",
                    source_snapshot=item.get("source_snapshot"),
                    created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
                )
            )

        capsule_map: dict[int, int] = {}
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
                created_at=_parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(capsule)
            db.flush()
            capsule_map[old_id] = capsule.id

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

        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}") from exc

    return {
        "status": "ok",
        "message": "Data imported successfully",
        "counts": {
            key: len(value) if isinstance(value, list) else 0
            for key, value in data.items()
        },
    }
