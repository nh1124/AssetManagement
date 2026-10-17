from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .money_storage import to_minor, money_client_currency, rule_amount_fields

from .. import models
from ..domain.errors import Invalid
from ..domain.money import Money
from ..domain.journal import Leg, coerce_leg, validate_legs
from ..domain.transfer import (
    EXPORT_VERSION,
    build_manifest,
    row_fields,
    data_counts,
    parse_date,
    parse_datetime,
    validate_import_payload,
    remap_nested_ids,
    remap_action_target_id,
)
from .data_health_service import check_data_health
from .budget_lines import assign_plan_line_identity
from .cache_service import invalidate_client
from .capsule_service import create_capsule_for_goal
from .registry_service import account_entry_type, account_line_type
from .life_scenario_service import seed_legacy_goal, copy_graph, get_goal


def _db_revision(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None


# A backup reads the schema as a whole; feature accessors would make their
# public interfaces depend on the backup format.
def export_client(db: Session, client: models.Client) -> dict:
    tx_ids = [
        row[0]
        for row in db.query(models.Transaction.id)
        .filter(models.Transaction.client_id == client.id)
        .all()
    ]

    exported_at = datetime.utcnow().isoformat()
    data = {
            "accounts": [
                row_fields(
                    account,
                    [
                        "id",
                        "name",
                        "account_type",
                        "parent_id",
                        "expected_return",
                        "institution",
                        "withdrawable_from_age",
                        "role",
                        "role_target_amount",
                        "liability_closing_day",
                        "liability_payment_day",
                        "liability_payment_month_offset",
                        "liability_payment_policy",
                        "liability_minimum_payment",
                        "liability_fixed_payment_amount",
                        "liability_installment_months",
                        "liability_revolving_rate",
                        "is_active",
                    ],
                )
                for account in db.query(models.Account)
                .filter(models.Account.client_id == client.id)
                .order_by(models.Account.id)
                .all()
            ],
            "products": [
                row_fields(
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
                        "depreciation_method",
                        "depreciation_annual_rate",
                        "depreciation_interval",
                        "depreciation_start_date",
                        "depreciation_expense_account_id",
                        "depreciation_asset_account_id",
                    ],
                )
                for product in db.query(models.Product)
                .filter(models.Product.client_id == client.id)
                .order_by(models.Product.id)
                .all()
            ],
            "product_depreciations": [
                row_fields(row, ["id", "product_id", "period", "transaction_id",
                                 "amount_minor", "created_at"])
                for row in db.query(models.ProductDepreciation)
                .filter(models.ProductDepreciation.client_id == client.id)
                .order_by(models.ProductDepreciation.product_id, models.ProductDepreciation.period)
                .all()
            ],
            "simulation_configs": [
                row_fields(
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
                        "horizon_years",
                    ],
                )
                for config in db.query(models.SimulationConfig)
                .filter(models.SimulationConfig.client_id == client.id)
                .order_by(models.SimulationConfig.id)
                .all()
            ],
            "recurring_transactions": [
                row_fields(
                    item,
                    [
                        "id",
                        "name",
                        "amount",
                        "currency",
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
                .filter(models.RecurringTransaction.client_id == client.id)
                .order_by(models.RecurringTransaction.id)
                .all()
            ],
            "registry_entries": [
                row_fields(
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
                .filter(models.RegistryEntry.client_id == client.id)
                .order_by(models.RegistryEntry.id)
                .all()
            ],
            "quick_templates": [
                row_fields(
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
                .filter(models.QuickTemplate.client_id == client.id)
                .order_by(models.QuickTemplate.id)
                .all()
            ],
            "transaction_batches": [
                row_fields(
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
                .filter(models.TransactionBatch.client_id == client.id)
                .order_by(models.TransactionBatch.id)
                .all()
            ],
            "life_events": [
                row_fields(
                    event,
                    [
                        "id",
                        "scenario_id",
                        "lineage",
                        "name",
                        "start_date",
                        "target_date",
                        "target_amount",
                        "priority",
                        "note",
                        "condition_mode",
                        "direction",
                        "account_id",
                        "active_plan_basis",
                        "active_plan_label",
                        "plan_status_override",
                        "budget_reflection",
                        "archived_at",
                        "created_at",
                    ],
                )
                for event in db.query(models.LifeEvent)
                .filter(models.LifeEvent.client_id == client.id)
                .order_by(models.LifeEvent.id)
                .all()
            ],
            "life_event_links": [
                row_fields(link, ["id", "from_event_id", "to_event_id", "kind", "offset_months", "note", "created_at"])
                for link in db.query(models.LifeEventLink)
                .filter(models.LifeEventLink.client_id == client.id)
                .order_by(models.LifeEventLink.id).all()
            ],
            "life_scenarios": [
                row_fields(row, ["id", "name", "annual_return", "inflation", "horizon_years", "monthly_savings", "is_goal", "created_at", "updated_at"])
                for row in db.query(models.LifeScenario).filter_by(client_id=client.id).order_by(models.LifeScenario.id).all()
            ],
            "life_scenario_account_returns": [
                row_fields(row, ["id", "scenario_id", "account_id", "annual_return"])
                for row in db.query(models.LifeScenarioAccountReturn).join(models.LifeScenario, models.LifeScenario.id == models.LifeScenarioAccountReturn.scenario_id)
                .filter(models.LifeScenario.client_id == client.id).order_by(models.LifeScenarioAccountReturn.id).all()
            ],
            "household_members": [
                row_fields(row, ["id", "name", "relation", "birth_date", "created_at"])
                for row in db.query(models.HouseholdMember).filter_by(client_id=client.id).order_by(models.HouseholdMember.id).all()
            ],
            "life_event_conditions": [
                row_fields(row, ["id", "life_event_id", "metric", "comparator", "threshold_minor", "threshold_number", "threshold_date", "reference_id", "note", "created_at"])
                for row in db.query(models.LifeEventCondition).filter_by(client_id=client.id).order_by(models.LifeEventCondition.id).all()
            ],
            "transactions": [
                row_fields(
                    transaction,
                    [
                        "id",
                        "date",
                        "description",
                        "amount",
                        "currency",
                        "batch_id",
                        "recurring_transaction_id",
                        "created_at",
                    ],
                )
                for transaction in db.query(models.Transaction)
                .filter(models.Transaction.client_id == client.id)
                .order_by(models.Transaction.id)
                .all()
            ],
            "journal_entries": [
                row_fields(entry, ["id", "transaction_id", "account_id", "capsule_id", "debit", "credit", "memo", "sort_order"])
                for entry in db.query(models.JournalEntry)
                .filter(models.JournalEntry.transaction_id.in_(tx_ids or [-1]))
                .order_by(models.JournalEntry.id)
                .all()
            ],
            "budget_plans": [
                row_fields(
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
                .filter(models.BudgetPlan.client_id == client.id)
                .order_by(models.BudgetPlan.sort_order, models.BudgetPlan.id)
                .all()
            ],
            "monthly_plan_lines": [
                row_fields(
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
                        "source_kind",
                        "identity_key",
                        "manual_override",
                        "cash_treatment",
                        "plan_id",
                        "is_active",
                        "created_at",
                        "updated_at",
                    ],
                )
                for line in db.query(models.MonthlyPlanLine)
                .filter(models.MonthlyPlanLine.client_id == client.id)
                .order_by(models.MonthlyPlanLine.target_period, models.MonthlyPlanLine.id)
                .all()
            ],
            "period_reviews": [
                row_fields(
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
                .filter(models.PeriodReview.client_id == client.id)
                .order_by(models.PeriodReview.start_date, models.PeriodReview.end_date)
                .all()
            ],
            "period_closes": [
                row_fields(close, ["id", "period", "closed_at", "note"])
                for close in db.query(models.PeriodClose).filter_by(client_id=client.id)
                .order_by(models.PeriodClose.period).all()
            ],
            "monthly_actions": [
                row_fields(
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
                .filter(models.MonthlyAction.client_id == client.id)
                .order_by(models.MonthlyAction.id)
                .all()
            ],
            "milestones": [
                row_fields(
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
                .filter(models.Milestone.client_id == client.id)
                .order_by(models.Milestone.id)
                .all()
            ],
            "capsules": [
                {
                    **row_fields(capsule, ["id", "name", "target_amount", "monthly_contribution"]),
                    **row_fields(capsule, [
                        "life_event_id", "capsule_type", "target_amount_source",
                        "monthly_contribution_source", "created_at",
                    ]),
                }
                for capsule in db.query(models.Capsule)
                .filter(models.Capsule.client_id == client.id)
                .order_by(models.Capsule.id)
                .all()
            ],
            "capsule_drawdowns": [
                row_fields(drawdown, ["id", "capsule_id", "transaction_id", "kind", "amount_minor", "note", "created_at"])
                for drawdown in db.query(models.CapsuleDrawdown)
                .filter(models.CapsuleDrawdown.client_id == client.id)
                .order_by(models.CapsuleDrawdown.id)
                .all()
            ],
            "capsule_funding_sources": [
                row_fields(source, ["id", "capsule_id", "account_id", "target_amount", "max_share_bp", "sort_order", "created_at", "updated_at"])
                for source in db.query(models.CapsuleFundingSource)
                .filter(models.CapsuleFundingSource.client_id == client.id)
                .order_by(models.CapsuleFundingSource.id)
                .all()
            ],
            "capsule_rules": [
                row_fields(
                    rule,
                    [
                        "id",
                        "capsule_id",
                        "trigger_type",
                        "trigger_category",
                        "trigger_description",
                        "source_mode",
                        "source_account_id",
                        "destination_account_id",
                        "amount_type",
                        "amount_value",
                        "is_active",
                        "created_at",
                    ],
                )
                for rule in db.query(models.CapsuleRule)
                .filter(models.CapsuleRule.client_id == client.id)
                .order_by(models.CapsuleRule.id)
                .all()
            ],
            "simulation_scenarios": [
                row_fields(
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
                .filter(models.SimulationScenario.client_id == client.id)
                .order_by(models.SimulationScenario.id)
                .all()
            ],
            "exchange_rates": [
                row_fields(
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
                .filter(models.ExchangeRate.client_id == client.id)
                .order_by(models.ExchangeRate.id)
                .all()
            ],
    }

    return {
        "version": EXPORT_VERSION,
        "exported_at": exported_at,
        "manifest": build_manifest(client.id, data, exported_at, _db_revision(db)),
        "client": {
            "id": client.id,
            "name": client.name,
            "username": client.username,
            "email": client.email,
            "general_settings": client.general_settings or {},
        },
        "health": check_data_health(db, client.id),
        "data": data,
    }


def import_client(
    db: Session,
    client: models.Client,
    *,
    data: dict[str, list[dict[str, Any]]],
    version: int | None,
    manifest: dict[str, Any] | None,
) -> dict:
    data = data or {}
    validation = validate_import_payload(data, version, manifest)
    if validation["error_count"]:
        raise Invalid(
            "Import payload validation failed",
            payload={
                "message": "Import payload validation failed",
                "validation": validation,
            },
        )

    link_map: dict[int, int] = {}
    scenario_map: dict[int, int] = {}
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
            .filter(models.Transaction.client_id == client.id)
            .all()
        ]

        if tx_ids:
            db.query(models.JournalEntry).filter(
                models.JournalEntry.transaction_id.in_(tx_ids)
            ).delete(synchronize_session=False)

        scenario_ids = db.query(models.LifeScenario.id).filter_by(client_id=client.id)
        db.query(models.LifeScenarioAccountReturn).filter(
            models.LifeScenarioAccountReturn.scenario_id.in_(scenario_ids),
        ).delete(synchronize_session=False)

        for model in [
            models.LifeEventCondition,
            models.HouseholdMember,
            models.LifeEventLink,
            models.ProductDepreciation,
            models.MonthlyPlanLine,
            models.PeriodReview,
            models.PeriodClose,
            models.MonthlyAction,
            models.CapsuleDrawdown,
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
            models.LifeScenario,
            models.Account,
        ]:
            db.query(model).filter(model.client_id == client.id).delete(
                synchronize_session=False
            )

        db.flush()

        # Legacy backups may contain balance; only their journal is authoritative.
        account_parent_updates: list[tuple[models.Account, int]] = []
        for item in data.get("accounts", []):
            old_id = int(item["id"])
            account = models.Account(
                client_id=client.id,
                name=item["name"],
                account_type=item["account_type"],
                expected_return=item.get("expected_return", 0.0),
                institution=item.get("institution", "none"),
                withdrawable_from_age=item.get("withdrawable_from_age"),
                role=item.get("role", "unassigned"),
                role_target_amount_minor=to_minor(item.get("role_target_amount"), money_client_currency(db, client.id)),
                liability_closing_day=item.get("liability_closing_day"),
                liability_payment_day=item.get("liability_payment_day"),
                liability_payment_month_offset=item.get("liability_payment_month_offset") or 0,
                liability_payment_policy=item.get("liability_payment_policy") or "full",
                liability_minimum_payment_minor=to_minor(item.get("liability_minimum_payment"), money_client_currency(db, client.id)),
                liability_fixed_payment_amount_minor=to_minor(item.get("liability_fixed_payment_amount"), money_client_currency(db, client.id)),
                liability_installment_months=item.get("liability_installment_months"),
                liability_revolving_rate=item.get("liability_revolving_rate"),
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
                client_id=client.id,
                name=item["name"],
                description=item.get("description"),
                is_default=item.get("is_default", False),
                sort_order=item.get("sort_order") or 0,
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=parse_datetime(item.get("updated_at")),
            )
            db.add(plan)
            db.flush()
            budget_plan_map[old_id] = plan.id

        product_map: dict[int, int] = {}
        product_funding_updates: list[tuple[models.Product, int]] = []
        for item in data.get("products", []):
            old_id = int(item["id"])
            product = models.Product(
                client_id=client.id,
                name=item["name"],
                category=item["category"],
                location=item.get("location"),
                last_unit_price_minor=to_minor(item.get("last_unit_price") or 0, money_client_currency(db, client.id)),
                units_per_purchase=item.get("units_per_purchase") or 1,
                frequency_days=item.get("frequency_days") or 0,
                last_purchase_date=parse_date(item.get("last_purchase_date")),
                is_asset=item.get("is_asset", False),
                lifespan_months=item.get("lifespan_months"),
                budget_account_id=account_map.get(item.get("budget_account_id")),
                budget_treatment=item.get("budget_treatment") or "auto",
                purchase_price_minor=to_minor(item.get("purchase_price"), money_client_currency(db, client.id)),
                purchase_date=parse_date(item.get("purchase_date")),
                depreciation_method=item.get("depreciation_method") or "none",
                depreciation_annual_rate=item.get("depreciation_annual_rate"),
                depreciation_interval=item.get("depreciation_interval") or "monthly",
                depreciation_start_date=parse_date(item.get("depreciation_start_date")),
                depreciation_expense_account_id=account_map.get(item.get("depreciation_expense_account_id")),
                depreciation_asset_account_id=account_map.get(item.get("depreciation_asset_account_id")),
            )
            db.add(product)
            db.flush()
            product_map[old_id] = product.id
            if item.get("funding_capsule_id"):
                product_funding_updates.append((product, int(item["funding_capsule_id"])))

        for item in data.get("simulation_configs", []):
            db.add(
                models.SimulationConfig(
                    client_id=client.id,
                    user_id=item.get("user_id", client.id),
                    annual_return=item.get("annual_return", 5.0),
                    tax_rate=item.get("tax_rate", 20.0),
                    is_nisa=item.get("is_nisa", True),
                    monthly_savings_minor=to_minor(item.get("monthly_savings", 100000), money_client_currency(db, client.id)),
                    volatility=item.get("volatility", 15.0),
                    inflation_rate=item.get("inflation_rate", 2.0),
                    horizon_years=item.get("horizon_years", 30),
                )
            )

        registry_map: dict[int, int] = {}
        registry_funding_updates: list[tuple[models.RegistryEntry, int]] = []
        for item in data.get("registry_entries", []):
            old_id = int(item["id"])
            entry = models.RegistryEntry(
                client_id=client.id,
                name=item["name"],
                entry_type=item.get("entry_type") or "service",
                category=item.get("category"),
                amount_minor=to_minor(item.get("amount") or 0, item.get("currency") or "JPY"),
                # Restore the backup's denomination; today's settings would rewrite history.
                currency=item.get("currency") or "JPY",
                frequency=item.get("frequency") or "Monthly",
                frequency_days=item.get("frequency_days"),
                day_of_month=item.get("day_of_month") or 1,
                month_of_year=item.get("month_of_year"),
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
                note=item.get("note"),
                start_period=item.get("start_period"),
                end_period=item.get("end_period"),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=parse_datetime(item.get("updated_at")),
            )
            db.add(entry)
            db.flush()
            registry_map[old_id] = entry.id
            if item.get("funding_capsule_id"):
                registry_funding_updates.append((entry, int(item["funding_capsule_id"])))

        backfilled_recurring = 0
        for item in data.get("recurring_transactions", []):
            old_id = int(item["id"])
            source_registry_id = registry_map.get(item.get("source_registry_entry_id"))
            backfilled_entry = None
            if source_registry_id is None:
                source_id = account_map.get(item.get("from_account_id"))
                destination_id = account_map.get(item.get("to_account_id"))
                source = db.get(models.Account, source_id) if source_id else None
                destination = db.get(models.Account, destination_id) if destination_id else None
                line_type = account_line_type(source, destination)
                backfilled_entry = models.RegistryEntry(
                    client_id=client.id,
                    name=item["name"],
                    amount_minor=to_minor(item.get("amount") or 0, item.get("currency") or "JPY"),
                    currency=item.get("currency") or "JPY",
                    frequency=item["frequency"],
                    day_of_month=item.get("day_of_month") or 1,
                    month_of_year=item.get("month_of_year"),
                    start_period=item.get("start_period"),
                    end_period=item.get("end_period"),
                    source_account_id=source_id,
                    destination_account_id=destination_id,
                    line_type=line_type,
                    entry_type=account_entry_type(source, destination),
                    budget_account_id=destination_id if line_type in {"expense", "debt_payment"} else None,
                    generate_recurring=True,
                    budget_active=True,
                    is_active=item.get("is_active", True),
                )
                db.add(backfilled_entry)
                db.flush()
                source_registry_id = backfilled_entry.id
                backfilled_recurring += 1
            recurring = models.RecurringTransaction(
                client_id=client.id,
                source_registry_entry_id=source_registry_id,
                name=item["name"],
                amount_minor=to_minor(item.get("amount") or 0, item.get("currency") or "JPY"),
                currency=item.get("currency") or "JPY",
                from_account_id=account_map.get(item.get("from_account_id")),
                to_account_id=account_map.get(item.get("to_account_id")),
                frequency=item["frequency"],
                day_of_month=item.get("day_of_month") or 1,
                month_of_year=item.get("month_of_year"),
                next_due_date=parse_date(item.get("next_due_date")),
                start_period=item.get("start_period"),
                end_period=item.get("end_period"),
                auto_post=item.get("auto_post", True),
                is_active=item.get("is_active", True),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(recurring)
            db.flush()
            recurring_map[old_id] = recurring.id
            if backfilled_entry is not None:
                backfilled_entry.source_recurring_transaction_id = recurring.id

        for item in data.get("registry_entries", []):
            entry = db.get(models.RegistryEntry, registry_map[int(item["id"])])
            entry.source_recurring_transaction_id = recurring_map.get(item.get("source_recurring_transaction_id"))

        if backfilled_recurring:
            validation["issues"].append({
                "severity": "warning",
                "code": "recurring_without_registry_backfilled",
                "detail": f"Created registry entries for {backfilled_recurring} recurring definitions without a restorable registry entry.",
                "collection": "recurring_transactions",
            })
            validation["warning_count"] += 1

        for item in data.get("quick_templates", []):
            old_id = int(item["id"])
            template = models.QuickTemplate(
                client_id=client.id,
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
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=parse_datetime(item.get("updated_at")),
            )
            db.add(template)
            db.flush()
            quick_template_map[old_id] = template.id

        for item in data.get("transaction_batches", []):
            old_id = int(item["id"])
            batch = models.TransactionBatch(
                client_id=client.id,
                quick_template_id=quick_template_map.get(item.get("quick_template_id")),
                label=item.get("label"),
                source=item.get("source") or "quick",
                input_payload=item.get("input_payload") or {},
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(batch)
            db.flush()
            batch_map[old_id] = batch.id

        if version is not None and version >= 21:
            for item in data.get("life_scenarios", []):
                scenario = models.LifeScenario(
                    client_id=client.id, name=item["name"], annual_return=item.get("annual_return", 5.0),
                    inflation=item.get("inflation", 2.0), horizon_years=item.get("horizon_years", 30),
                    monthly_savings_minor=None if item.get("monthly_savings") is None
                    else to_minor(item["monthly_savings"], money_client_currency(db, client.id)),
                    is_goal=item.get("is_goal", False),
                    created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=parse_datetime(item.get("updated_at")) or datetime.utcnow(),
                )
                db.add(scenario)
                db.flush()
                scenario_map[int(item["id"])] = scenario.id
            for item in data.get("life_scenario_account_returns", []):
                db.add(models.LifeScenarioAccountReturn(
                    scenario_id=scenario_map[int(item["scenario_id"])], account_id=account_map[int(item["account_id"])], annual_return=item["annual_return"],
                ))
        legacy_graph = version is None or version < 22
        restored_goal = get_goal(db, client.id)
        if legacy_graph and data.get("life_events") and restored_goal is None:
            restored_goal = seed_legacy_goal(db, client.id)

        for item in data.get("life_events", []):
            old_id = int(item["id"])
            event = models.LifeEvent(
                client_id=client.id,
                scenario_id=restored_goal.id if legacy_graph else scenario_map[int(item["scenario_id"])],
                lineage=str(uuid4()) if legacy_graph else item["lineage"],
                name=item["name"],
                start_date=parse_date(item.get("start_date")),
                target_date=parse_date(item.get("target_date")),
                target_amount_minor=to_minor(item.get("target_amount") or 0, money_client_currency(db, client.id)),
                priority=item.get("priority") or 2,
                note=item.get("note"),
                condition_mode=item.get("condition_mode", "all"),
                direction=item.get("direction", "expense"),
                account_id=account_map.get(item.get("account_id")),
                active_plan_basis=item.get("active_plan_basis") or "milestone",
                active_plan_label=item.get("active_plan_label"),
                plan_status_override=item.get("plan_status_override"),
                budget_reflection=item.get("budget_reflection"),
                archived_at=parse_datetime(item.get("archived_at")),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(event)
            db.flush()
            event_map[old_id] = event.id

        for item in data.get("life_event_links", []):
            if legacy_graph and item["kind"] == "alternative":
                logging.getLogger(__name__).warning("Converting restored alternative life-event link to after: %s", item["id"])
            link = models.LifeEventLink(
                client_id=client.id,
                from_event_id=event_map[int(item["from_event_id"])],
                to_event_id=event_map[int(item["to_event_id"])],
                kind="after" if legacy_graph else item["kind"], offset_months=item.get("offset_months", 0),
                note=item.get("note"),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(link)
            db.flush()
            link_map[int(item["id"])] = link.id

        for item in data.get("transactions", []):
            old_id = int(item["id"])
            transaction = models.Transaction(
                client_id=client.id,
                date=parse_date(item.get("date")),
                description=item["description"],
                amount_minor=Money.from_major(str(item.get("amount") or 0), item.get("currency") or "JPY").minor,
                currency=item.get("currency") or "JPY",
                # from_account_id / to_account_id in a v6 or older payload are
                # ignored: the journal_entries below are the accounts, and they
                # were already required to balance.
                batch_id=batch_map.get(item.get("batch_id")),
                recurring_transaction_id=recurring_map.get(item.get("recurring_transaction_id")),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(transaction)
            db.flush()
            transaction_map[old_id] = transaction.id

        for item in data.get("product_depreciations", []):
            # Both ends must already be mapped: a posting names a product and
            # the entry that carried it, and is meaningless without either.
            product_id = product_map.get(int(item["product_id"]))
            transaction_id = transaction_map.get(int(item["transaction_id"]))
            if product_id is None or transaction_id is None:
                continue
            db.add(models.ProductDepreciation(
                client_id=client.id, product_id=product_id, transaction_id=transaction_id,
                period=item["period"], amount_minor=int(item["amount_minor"]),
                created_at=parse_datetime(item.get("created_at")),
            ))

        for item in data.get("period_closes", []):
            # Preserve close instants so restoration does not hide late entries.
            db.add(models.PeriodClose(
                client_id=client.id, period=item["period"],
                closed_at=parse_datetime(item["closed_at"]), note=item.get("note"),
            ))

        for item in data.get("period_reviews", []):
            db.add(
                models.PeriodReview(
                    client_id=client.id,
                    start_date=parse_date(item.get("start_date")),
                    end_date=parse_date(item.get("end_date")),
                    label=item.get("label") or "",
                    reflection=item.get("reflection") or "",
                    next_actions=item.get("next_actions") or "",
                    created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=parse_datetime(item.get("updated_at")),
                )
            )

        milestone_map: dict[int, int] = {}
        for item in data.get("milestones", []):
            old_id = int(item["id"])
            milestone = models.Milestone(
                client_id=client.id,
                life_event_id=event_map.get(item.get("life_event_id")),
                date=parse_date(item.get("date")),
                target_amount_minor=to_minor(item.get("target_amount") or 0, money_client_currency(db, client.id)),
                note=item.get("note"),
                source=item.get("source") or "manual",
                source_snapshot=item.get("source_snapshot"),
                is_active_plan=item.get("is_active_plan", True),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(milestone)
            db.flush()
            milestone_map[old_id] = milestone.id

        for item in data.get("simulation_scenarios", []):
            life_event_id = event_map.get(item.get("life_event_id"))
            if life_event_id:
                db.add(
                    models.SimulationScenario(
                        client_id=client.id,
                        life_event_id=life_event_id,
                        name=item["name"],
                        description=item.get("description"),
                        annual_return=item.get("annual_return") or 5.0,
                        inflation=item.get("inflation") or 2.0,
                        monthly_savings_minor=to_minor(item.get("monthly_savings"), money_client_currency(db, client.id)),
                        contribution_schedule=item.get("contribution_schedule") or [],
                        allocation_mode=item.get("allocation_mode") or "direct",
                        created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_datetime(item.get("updated_at")),
                    )
                )

        for item in data.get("capsules", []):
            old_id = int(item["id"])
            capsule = models.Capsule(
                client_id=client.id,
                name=item["name"],
                target_amount_minor=to_minor(item.get("target_amount") or 0, money_client_currency(db, client.id)),
                monthly_contribution_minor=to_minor(item.get("monthly_contribution") or 0, money_client_currency(db, client.id)),
                life_event_id=event_map.get(item.get("life_event_id")),
                capsule_type=item.get("capsule_type") or ("life_event" if item.get("life_event_id") else "manual"),
                target_amount_source=item.get("target_amount_source") or "manual",
                monthly_contribution_source=item.get("monthly_contribution_source") or "manual",
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(capsule)
            db.flush()
            capsule_map[old_id] = capsule.id

        for item in data.get("journal_entries", []):
            transaction_id = transaction_map.get(item.get("transaction_id"))
            account_id = account_map.get(item.get("account_id"))
            if transaction_id and account_id:
                transaction = db.get(models.Transaction, transaction_id)
                leg = coerce_leg({**item, "account_id": account_id}, transaction.currency)
                db.add(
                    models.JournalEntry(
                        transaction_id=transaction_id,
                        account_id=account_id,
                        capsule_id=capsule_map.get(item.get("capsule_id")),
                        debit_minor=leg.debit,
                        credit_minor=leg.credit,
                        memo=item.get("memo"),
                        sort_order=item.get("sort_order"),
                    )
                )

        db.flush()
        for transaction_id in transaction_map.values():
            transaction = db.query(models.Transaction).filter(
                models.Transaction.id == transaction_id
            ).one()
            entries = db.query(models.JournalEntry).filter(
                models.JournalEntry.transaction_id == transaction_id
            ).all()
            if len(entries) < 2:
                raise ValueError(f"Transaction {transaction_id} has fewer than two journal entries")
            try:
                validate_legs([
                    Leg(entry.account_id, entry.debit_minor, entry.credit_minor) for entry in entries
                ], transaction.amount_minor)
            except ValueError as exc:
                raise ValueError(f"Transaction {transaction_id}: {exc}") from exc

        for product, old_capsule_id in product_funding_updates:
            product.funding_capsule_id = capsule_map.get(old_capsule_id)

        for registry_entry, old_capsule_id in registry_funding_updates:
            registry_entry.funding_capsule_id = capsule_map.get(old_capsule_id)

        if version is None or version < 21:
            # Only older formats need capsule repair. V21+ restores the exact
            # capsule collection, including stories with no real-money earmarks.
            for event in (
                db.query(models.LifeEvent)
                .filter(models.LifeEvent.client_id == client.id, models.LifeEvent.direction == "expense",
                        models.LifeEvent.scenario_id == (restored_goal.id if restored_goal else -1))
                .all()
            ):
                create_capsule_for_goal(db, client.id, event)

        for item in data.get("capsule_drawdowns", []):
            db.add(models.CapsuleDrawdown(
                client_id=client.id,
                capsule_id=capsule_map[int(item["capsule_id"])],
                transaction_id=transaction_map[int(item["transaction_id"])],
                kind=item["kind"], amount_minor=item["amount_minor"],
                note=item.get("note"),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            ))

        for item in data.get("capsule_rules", []):
            capsule_id = capsule_map.get(item.get("capsule_id"))
            if capsule_id:
                db.add(
                    models.CapsuleRule(
                        client_id=client.id,
                        capsule_id=capsule_id,
                        trigger_type=item["trigger_type"],
                        trigger_category=item.get("trigger_category"),
                        trigger_description=item.get("trigger_description"),
                        source_mode=item.get("source_mode") or "transaction_account",
                        source_account_id=account_map.get(item.get("source_account_id")),
                        destination_account_id=account_map.get(item.get("destination_account_id")),
                        amount_type=item.get("amount_type") or "fixed",
                        **rule_amount_fields(item.get("amount_value") or 0, item.get("amount_type") or "fixed", money_client_currency(db, client.id)),
                        is_active=item.get("is_active", True),
                        created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    )
                )

        for item in data.get("capsule_funding_sources", []):
            capsule_id = capsule_map.get(item.get("capsule_id"))
            account_id = account_map.get(item.get("account_id"))
            if capsule_id and account_id:
                db.add(
                    models.CapsuleFundingSource(
                        client_id=client.id,
                        capsule_id=capsule_id,
                        account_id=account_id,
                        target_amount_minor=to_minor(
                            item.get("target_amount") or 0, money_client_currency(db, client.id),
                        ),
                        sort_order=item.get("sort_order") or 0,
                        max_share_bp=item.get("max_share_bp"),
                        created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                        updated_at=parse_datetime(item.get("updated_at")) or datetime.utcnow(),
                    )
                )

        monthly_plan_line_map: dict[int, int] = {}
        active_plan_line_identities: dict[str, models.MonthlyPlanLine] = {}
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
            account_id = account_map.get(item.get("account_id"))
            source_account_id = account_map.get(item.get("source_account_id"))
            source_kind = item.get("source_kind") or item.get("source") or "manual"
            if source_kind == "recurrence":
                source_kind = "recurring"
            line = models.MonthlyPlanLine(
                client_id=client.id,
                target_period=item["target_period"],
                line_type=item["line_type"],
                target_type=target_type,
                target_id=target_id,
                account_id=account_id,
                source_account_id=source_account_id,
                name=item.get("name"),
                amount_minor=to_minor(item.get("amount") or 0, money_client_currency(db, client.id)),
                source=item.get("source") or "manual",
                source_kind=source_kind,
                manual_override=item.get("manual_override", False),
                cash_treatment=item.get("cash_treatment") or "auto",
                plan_id=budget_plan_map.get(item.get("plan_id")),
                is_active=item.get("is_active", True),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                updated_at=parse_datetime(item.get("updated_at")),
            )
            assign_plan_line_identity(line)
            if line.is_active and line.identity_key:
                previous = active_plan_line_identities.get(line.identity_key)
                if previous:
                    previous.is_active = False
                    db.flush()
                active_plan_line_identities[line.identity_key] = line
            db.add(line)
            db.flush()
            monthly_plan_line_map[old_id] = line.id

        for item in data.get("exchange_rates", []):
            db.add(
                models.ExchangeRate(
                    client_id=client.id,
                    base_currency=(item.get("base_currency") or "JPY").upper(),
                    quote_currency=(item.get("quote_currency") or "JPY").upper(),
                    rate=item.get("rate") or 1.0,
                    as_of_date=parse_date(item.get("as_of_date")) or date.today(),
                    source=item.get("source") or "manual",
                    created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    updated_at=parse_datetime(item.get("updated_at")),
                )
            )

        member_map: dict[int, int] = {}
        for item in data.get("household_members", []):
            member = models.HouseholdMember(
                client_id=client.id, name=item["name"], relation=item.get("relation"),
                birth_date=parse_date(item["birth_date"]),
                created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            )
            db.add(member)
            db.flush()
            member_map[int(item["id"])] = member.id
        condition_reference_maps = {
            "account_balance": account_map, "capsule_claim": capsule_map,
            "goal_progress": event_map, "member_age": member_map,
        }
        for item in data.get("life_event_conditions", []):
            # Never keep a dangling source id: it might identify an unrelated restored fact.
            reference_id = condition_reference_maps.get(item["metric"], {}).get(item.get("reference_id"))
            db.add(models.LifeEventCondition(
                client_id=client.id, life_event_id=event_map[int(item["life_event_id"])],
                metric=item["metric"], comparator=item["comparator"],
                threshold_minor=item.get("threshold_minor"), threshold_number=item.get("threshold_number"),
                threshold_date=parse_date(item.get("threshold_date")), reference_id=reference_id,
                note=item.get("note"), created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
            ))

        if legacy_graph and restored_goal is not None:
            # A shared graph was every story; copies are made after all children exist.
            db.flush()
            for story in db.query(models.LifeScenario).filter(
                models.LifeScenario.client_id == client.id, models.LifeScenario.id != restored_goal.id,
            ).all():
                copy_graph(db, client.id, restored_goal.id, story.id)

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
                    client_id=client.id,
                    source_period=item["source_period"],
                    target_period=item.get("target_period"),
                    proposal_id=item["proposal_id"],
                    kind=item["kind"],
                    description=item.get("description") or "",
                    amount_minor=to_minor(item.get("amount"), money_client_currency(db, client.id)),
                    target_id=remap_action_target_id(item, action_key_maps),
                    payload=remap_nested_ids(item.get("payload") or {}, action_key_maps),
                    result=remap_nested_ids(item.get("result") or {}, action_key_maps),
                    status=item.get("status") or "pending",
                    idempotency_key=item.get("idempotency_key") or f"import:{client.id}:{item['id']}",
                    created_at=parse_datetime(item.get("created_at")) or datetime.utcnow(),
                    applied_at=parse_datetime(item.get("applied_at")),
                )
            )

        db.commit()
        invalidate_client(client.id)
    except Exception as exc:
        db.rollback()
        raise Invalid(f"Import failed: {exc}") from exc

    return {
        "status": "ok",
        "message": "Data imported successfully",
        "counts": data_counts(data),
        "validation": validation,
        "health": check_data_health(db, client.id),
    }
